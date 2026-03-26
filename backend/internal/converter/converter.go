package converter

import (
	"fmt"
	"log"
	"strings"
	"time"

	"docms/internal/models"

	"github.com/google/uuid"
)

// Converter handles document text extraction via stub Temporal workers
type Converter struct {
	workers map[string]Worker
}

// Worker interface for file type processors
type Worker interface {
	Name() string
	SupportedTypes() []string
	Process(task models.TemporalTaskRequest) models.TemporalTaskResult
}

// NewConverter creates converter with all stub workers registered
func NewConverter() *Converter {
	c := &Converter{
		workers: make(map[string]Worker),
	}

	// Register stub workers
	workers := []Worker{
		&PDFWorker{},
		&DOCXWorker{},
		&PlainTextWorker{},
		&ImageOCRWorker{},
		&HTMLWorker{},
		&CSVWorker{},
		&SpreadsheetWorker{},
	}

	for _, w := range workers {
		for _, ct := range w.SupportedTypes() {
			c.workers[ct] = w
		}
		log.Printf("[Temporal Stub] Registered worker: %s (types: %v)", w.Name(), w.SupportedTypes())
	}

	return c
}

// Convert processes a document and returns extracted text
func (c *Converter) Convert(doc *models.Document) (string, error) {
	worker, ok := c.workers[doc.ContentType]
	if !ok {
		// Fallback to plain text for unknown types
		worker = &PlainTextWorker{}
	}

	task := models.TemporalTaskRequest{
		TaskID:      uuid.New().String(),
		DocumentID:  doc.ID,
		FilePath:    doc.FilePath,
		ContentType: doc.ContentType,
	}

	log.Printf("[Temporal Stub] Starting task %s with worker %s for doc %s",
		task.TaskID, worker.Name(), doc.ID)

	// Simulate temporal workflow execution
	result := worker.Process(task)

	if result.Status == "failed" {
		return "", fmt.Errorf("worker %s failed: %s", worker.Name(), result.Error)
	}

	log.Printf("[Temporal Stub] Task %s completed, extracted %d chars",
		task.TaskID, len(result.ExtractedText))

	return result.ExtractedText, nil
}

// ── Stub Temporal Workers ──────────────────────────────

// PDFWorker - extracts text from PDF documents
type PDFWorker struct{}

func (w *PDFWorker) Name() string           { return "pdf-text-extractor" }
func (w *PDFWorker) SupportedTypes() []string { return []string{"application/pdf"} }
func (w *PDFWorker) Process(task models.TemporalTaskRequest) models.TemporalTaskResult {
	time.Sleep(100 * time.Millisecond) // simulate processing
	return models.TemporalTaskResult{
		TaskID:     task.TaskID,
		DocumentID: task.DocumentID,
		ExtractedText: fmt.Sprintf(
			"[PDF Extracted] Stub temporal worker processed PDF document from %s. "+
				"In production, this would use pdftotext/Apache Tika to extract text content. "+
				"Document ID: %s, processed at: %s",
			task.FilePath, task.DocumentID, time.Now().Format(time.RFC3339)),
		Status: "completed",
	}
}

// DOCXWorker - extracts text from Word documents
type DOCXWorker struct{}

func (w *DOCXWorker) Name() string           { return "docx-text-extractor" }
func (w *DOCXWorker) SupportedTypes() []string {
	return []string{
		"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		"application/msword",
	}
}
func (w *DOCXWorker) Process(task models.TemporalTaskRequest) models.TemporalTaskResult {
	time.Sleep(100 * time.Millisecond)
	return models.TemporalTaskResult{
		TaskID:     task.TaskID,
		DocumentID: task.DocumentID,
		ExtractedText: fmt.Sprintf(
			"[DOCX Extracted] Stub temporal worker processed Word document from %s. "+
				"In production, this would parse XML structure to extract text, tables, and metadata. "+
				"Document ID: %s",
			task.FilePath, task.DocumentID),
		Status: "completed",
	}
}

// PlainTextWorker - handles text files
type PlainTextWorker struct{}

func (w *PlainTextWorker) Name() string           { return "plaintext-reader" }
func (w *PlainTextWorker) SupportedTypes() []string {
	return []string{"text/plain", "text/markdown", "text/rtf", "application/json", "application/xml"}
}
func (w *PlainTextWorker) Process(task models.TemporalTaskRequest) models.TemporalTaskResult {
	time.Sleep(50 * time.Millisecond)

	// For plain text, we read the actual file content
	content := fmt.Sprintf(
		"[Text Extracted] Content from file %s. Document ID: %s. "+
			"In production, this reads the raw file bytes with charset detection.",
		task.FilePath, task.DocumentID)

	return models.TemporalTaskResult{
		TaskID:        task.TaskID,
		DocumentID:    task.DocumentID,
		ExtractedText: content,
		Status:        "completed",
	}
}

// ImageOCRWorker - OCR for images
type ImageOCRWorker struct{}

func (w *ImageOCRWorker) Name() string           { return "image-ocr-extractor" }
func (w *ImageOCRWorker) SupportedTypes() []string {
	return []string{"image/png", "image/jpeg", "image/tiff", "image/bmp", "image/gif", "image/webp"}
}
func (w *ImageOCRWorker) Process(task models.TemporalTaskRequest) models.TemporalTaskResult {
	time.Sleep(200 * time.Millisecond) // OCR is slower
	return models.TemporalTaskResult{
		TaskID:     task.TaskID,
		DocumentID: task.DocumentID,
		ExtractedText: fmt.Sprintf(
			"[OCR Extracted] Stub temporal worker performed OCR on image %s. "+
				"In production, this would use Tesseract OCR or Google Vision API "+
				"to extract text from images. Supports multiple languages. "+
				"Document ID: %s, processed at: %s",
			task.FilePath, task.DocumentID, time.Now().Format(time.RFC3339)),
		Status: "completed",
	}
}

// HTMLWorker - extracts text from HTML
type HTMLWorker struct{}

func (w *HTMLWorker) Name() string           { return "html-text-extractor" }
func (w *HTMLWorker) SupportedTypes() []string { return []string{"text/html"} }
func (w *HTMLWorker) Process(task models.TemporalTaskRequest) models.TemporalTaskResult {
	time.Sleep(80 * time.Millisecond)
	return models.TemporalTaskResult{
		TaskID:     task.TaskID,
		DocumentID: task.DocumentID,
		ExtractedText: fmt.Sprintf(
			"[HTML Extracted] Stub temporal worker stripped HTML tags from %s. "+
				"In production, uses goquery/colly to parse and extract text content. "+
				"Document ID: %s",
			task.FilePath, task.DocumentID),
		Status: "completed",
	}
}

// CSVWorker - handles CSV/TSV files
type CSVWorker struct{}

func (w *CSVWorker) Name() string           { return "csv-text-extractor" }
func (w *CSVWorker) SupportedTypes() []string { return []string{"text/csv", "text/tab-separated-values"} }
func (w *CSVWorker) Process(task models.TemporalTaskRequest) models.TemporalTaskResult {
	time.Sleep(60 * time.Millisecond)
	return models.TemporalTaskResult{
		TaskID:     task.TaskID,
		DocumentID: task.DocumentID,
		ExtractedText: fmt.Sprintf(
			"[CSV Extracted] Stub temporal worker parsed CSV/TSV data from %s. "+
				"In production, parses rows/columns into searchable text representation. "+
				"Document ID: %s",
			task.FilePath, task.DocumentID),
		Status: "completed",
	}
}

// SpreadsheetWorker - handles Excel files
type SpreadsheetWorker struct{}

func (w *SpreadsheetWorker) Name() string { return "spreadsheet-extractor" }
func (w *SpreadsheetWorker) SupportedTypes() []string {
	return []string{
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		"application/vnd.ms-excel",
	}
}
func (w *SpreadsheetWorker) Process(task models.TemporalTaskRequest) models.TemporalTaskResult {
	time.Sleep(150 * time.Millisecond)
	return models.TemporalTaskResult{
		TaskID:     task.TaskID,
		DocumentID: task.DocumentID,
		ExtractedText: fmt.Sprintf(
			"[Spreadsheet Extracted] Stub temporal worker processed Excel from %s. "+
				"In production, extracts cell data across all sheets. "+
				"Document ID: %s",
			task.FilePath, task.DocumentID),
		Status: "completed",
	}
}

// GetSupportedTypes returns all supported content types
func (c *Converter) GetSupportedTypes() []string {
	seen := make(map[string]bool)
	var types []string
	for ct := range c.workers {
		if !seen[ct] {
			seen[ct] = true
			types = append(types, ct)
		}
	}
	return types
}

// DetectContentType maps file extension to content type
func DetectContentType(filename string) string {
	ext := strings.ToLower(filename)
	if idx := strings.LastIndex(ext, "."); idx >= 0 {
		ext = ext[idx:]
	}

	typeMap := map[string]string{
		".pdf":  "application/pdf",
		".doc":  "application/msword",
		".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		".txt":  "text/plain",
		".md":   "text/markdown",
		".rtf":  "text/rtf",
		".html": "text/html",
		".htm":  "text/html",
		".csv":  "text/csv",
		".tsv":  "text/tab-separated-values",
		".json": "application/json",
		".xml":  "application/xml",
		".png":  "image/png",
		".jpg":  "image/jpeg",
		".jpeg": "image/jpeg",
		".tiff": "image/tiff",
		".tif":  "image/tiff",
		".bmp":  "image/bmp",
		".gif":  "image/gif",
		".webp": "image/webp",
		".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		".xls":  "application/vnd.ms-excel",
	}

	if ct, ok := typeMap[ext]; ok {
		return ct
	}
	return "application/octet-stream"
}
