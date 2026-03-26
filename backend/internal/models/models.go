package models

import "time"

// Classification levels
type Classification string

const (
	ClassPublic  Classification = "public"
	ClassPrivate Classification = "private"
)

// ACL permissions
type Permission string

const (
	PermPublicSearchRead  Permission = "public_search_read"
	PermPublicUpload      Permission = "public_upload"
	PermPrivateSearchRead Permission = "private_search_read"
	PermPrivateUpload     Permission = "private_upload"
)

// User represents a system user
type User struct {
	ID             string       `json:"id"`
	Username       string       `json:"username"`
	HashedPassword string       `json:"-"`
	Permissions    []Permission `json:"permissions"`
	CreatedAt      time.Time    `json:"created_at"`
}

// Document represents a stored document
type Document struct {
	ID             string         `json:"id"`
	UserID         string         `json:"user_id"`
	Filename       string         `json:"filename"`
	ContentType    string         `json:"content_type"`
	Classification Classification `json:"classification"`
	ExtractedText  string         `json:"extracted_text"`
	Status         string         `json:"status"` // pending, processing, completed, failed
	FilePath       string         `json:"file_path"`
	CreatedAt      time.Time      `json:"created_at"`
	UpdatedAt      time.Time      `json:"updated_at"`
}

// ElasticDocument is what gets indexed
type ElasticDocument struct {
	DocID          string         `json:"doc_id"`
	UserID         string         `json:"user_id"`
	Filename       string         `json:"filename"`
	Classification Classification `json:"classification"`
	Content        string         `json:"content"`
	ContentType    string         `json:"content_type"`
	IndexedAt      time.Time      `json:"indexed_at"`
}

// LoginRequest for auth
type LoginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// LoginResponse with JWT
type LoginResponse struct {
	Token string `json:"token"`
	User  User   `json:"user"`
}

// RegisterRequest for creating users
type RegisterRequest struct {
	Username       string       `json:"username"`
	Password       string       `json:"password"`
	Permissions    []Permission `json:"permissions"`
}

// UploadResponse after file upload
type UploadResponse struct {
	DocumentID string `json:"document_id"`
	Status     string `json:"status"`
	Message    string `json:"message"`
}

// SearchRequest for querying documents
type SearchRequest struct {
	Query string `json:"query"`
	Page  int    `json:"page"`
	Size  int    `json:"size"`
}

// SearchResult from elasticsearch
type SearchResult struct {
	Total    int              `json:"total"`
	Results  []SearchHit      `json:"results"`
}

type SearchHit struct {
	DocID          string         `json:"doc_id"`
	Filename       string         `json:"filename"`
	Classification Classification `json:"classification"`
	Content        string         `json:"content"`
	Score          float64        `json:"score"`
	Highlight      string         `json:"highlight"`
}

// TemporalTaskRequest for worker stubs
type TemporalTaskRequest struct {
	TaskID      string `json:"task_id"`
	DocumentID  string `json:"document_id"`
	FilePath    string `json:"file_path"`
	ContentType string `json:"content_type"`
}

// TemporalTaskResult from worker stubs
type TemporalTaskResult struct {
	TaskID        string `json:"task_id"`
	DocumentID    string `json:"document_id"`
	ExtractedText string `json:"extracted_text"`
	Status        string `json:"status"`
	Error         string `json:"error,omitempty"`
}

// CanSearch checks if user can search a classification level
func (u *User) CanSearch(class Classification) bool {
	for _, p := range u.Permissions {
		if class == ClassPublic && p == PermPublicSearchRead {
			return true
		}
		if class == ClassPrivate && p == PermPrivateSearchRead {
			return true
		}
	}
	return false
}

// CanUpload checks if user can upload at a classification level
func (u *User) CanUpload(class Classification) bool {
	for _, p := range u.Permissions {
		if class == ClassPublic && p == PermPublicUpload {
			return true
		}
		if class == ClassPrivate && p == PermPrivateUpload {
			return true
		}
	}
	return false
}

// GetSearchableClassifications returns classifications user can search
func (u *User) GetSearchableClassifications() []Classification {
	var classes []Classification
	for _, p := range u.Permissions {
		if p == PermPublicSearchRead {
			classes = append(classes, ClassPublic)
		}
		if p == PermPrivateSearchRead {
			classes = append(classes, ClassPrivate)
		}
	}
	return classes
}
