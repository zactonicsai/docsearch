package elasticsearch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"docms/internal/models"

	"github.com/elastic/go-elasticsearch/v8"
)

const IndexName = "documents"

type Client struct {
	es *elasticsearch.Client
}

func NewClient(url string) (*Client, error) {
	cfg := elasticsearch.Config{
		Addresses: []string{url},
	}

	es, err := elasticsearch.NewClient(cfg)
	if err != nil {
		return nil, fmt.Errorf("create es client: %w", err)
	}

	c := &Client{es: es}

	// Wait for ES to be ready
	for i := 0; i < 30; i++ {
		res, err := es.Info()
		if err == nil && !res.IsError() {
			res.Body.Close()
			break
		}
		log.Printf("Waiting for Elasticsearch... attempt %d", i+1)
		time.Sleep(2 * time.Second)
	}

	if err := c.createIndex(); err != nil {
		return nil, fmt.Errorf("create index: %w", err)
	}

	return c, nil
}

func (c *Client) createIndex() error {
	mapping := `{
		"settings": {
			"number_of_shards": 1,
			"number_of_replicas": 0,
			"analysis": {
				"analyzer": {
					"content_analyzer": {
						"type": "custom",
						"tokenizer": "standard",
						"filter": ["lowercase", "stop", "snowball"]
					}
				}
			}
		},
		"mappings": {
			"properties": {
				"doc_id":          { "type": "keyword" },
				"user_id":         { "type": "keyword" },
				"filename":        { "type": "text", "fields": { "keyword": { "type": "keyword" } } },
				"classification":  { "type": "keyword" },
				"content":         { "type": "text", "analyzer": "content_analyzer" },
				"content_type":    { "type": "keyword" },
				"indexed_at":      { "type": "date" }
			}
		}
	}`

	// Check if index exists
	res, err := c.es.Indices.Exists([]string{IndexName})
	if err != nil {
		return err
	}
	res.Body.Close()

	if res.StatusCode == 200 {
		return nil // index already exists
	}

	res, err = c.es.Indices.Create(IndexName, c.es.Indices.Create.WithBody(strings.NewReader(mapping)))
	if err != nil {
		return err
	}
	defer res.Body.Close()

	if res.IsError() {
		return fmt.Errorf("create index error: %s", res.String())
	}

	return nil
}

func (c *Client) IndexDocument(doc models.ElasticDocument) error {
	data, err := json.Marshal(doc)
	if err != nil {
		return err
	}

	res, err := c.es.Index(
		IndexName,
		bytes.NewReader(data),
		c.es.Index.WithDocumentID(doc.DocID),
		c.es.Index.WithRefresh("true"),
	)
	if err != nil {
		return fmt.Errorf("index document: %w", err)
	}
	defer res.Body.Close()

	if res.IsError() {
		return fmt.Errorf("index error: %s", res.String())
	}

	return nil
}

func (c *Client) Search(ctx context.Context, query string, classifications []models.Classification, page, size int) (*models.SearchResult, error) {
	if size <= 0 {
		size = 10
	}
	if page <= 0 {
		page = 1
	}
	from := (page - 1) * size

	// Build classification filter
	classStrings := make([]string, len(classifications))
	for i, c := range classifications {
		classStrings[i] = fmt.Sprintf(`"%s"`, c)
	}

	searchBody := fmt.Sprintf(`{
		"from": %d,
		"size": %d,
		"query": {
			"bool": {
				"must": [
					{
						"multi_match": {
							"query": %q,
							"fields": ["content", "filename"],
							"fuzziness": "AUTO"
						}
					}
				],
				"filter": [
					{
						"terms": {
							"classification": [%s]
						}
					}
				]
			}
		},
		"highlight": {
			"fields": {
				"content": {
					"fragment_size": 200,
					"number_of_fragments": 1
				}
			}
		}
	}`, from, size, query, strings.Join(classStrings, ","))

	res, err := c.es.Search(
		c.es.Search.WithContext(ctx),
		c.es.Search.WithIndex(IndexName),
		c.es.Search.WithBody(strings.NewReader(searchBody)),
	)
	if err != nil {
		return nil, fmt.Errorf("search: %w", err)
	}
	defer res.Body.Close()

	if res.IsError() {
		return nil, fmt.Errorf("search error: %s", res.String())
	}

	var result struct {
		Hits struct {
			Total struct {
				Value int `json:"value"`
			} `json:"total"`
			Hits []struct {
				Source    models.ElasticDocument `json:"_source"`
				Score    float64                `json:"_score"`
				Highlight map[string][]string   `json:"highlight"`
			} `json:"hits"`
		} `json:"hits"`
	}

	if err := json.NewDecoder(res.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode: %w", err)
	}

	searchResult := &models.SearchResult{
		Total: result.Hits.Total.Value,
	}

	for _, hit := range result.Hits.Hits {
		h := models.SearchHit{
			DocID:          hit.Source.DocID,
			Filename:       hit.Source.Filename,
			Classification: hit.Source.Classification,
			Content:        hit.Source.Content,
			Score:          hit.Score,
		}
		if highlights, ok := hit.Highlight["content"]; ok && len(highlights) > 0 {
			h.Highlight = highlights[0]
		}
		searchResult.Results = append(searchResult.Results, h)
	}

	return searchResult, nil
}

func (c *Client) GetDocumentCount() (int, error) {
	res, err := c.es.Count(c.es.Count.WithIndex(IndexName))
	if err != nil {
		return 0, err
	}
	defer res.Body.Close()

	var result struct {
		Count int `json:"count"`
	}
	json.NewDecoder(res.Body).Decode(&result)
	return result.Count, nil
}
