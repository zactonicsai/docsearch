package auth

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"time"

	"docms/internal/models"

	"github.com/google/uuid"
	_ "github.com/mattn/go-sqlite3"
	"golang.org/x/crypto/bcrypt"
)

type AuthDB struct {
	db *sql.DB
}

func NewAuthDB(dbPath string) (*AuthDB, error) {
	db, err := sql.Open("sqlite3", dbPath+"?_journal_mode=WAL")
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}

	a := &AuthDB{db: db}
	if err := a.migrate(); err != nil {
		return nil, fmt.Errorf("migrate: %w", err)
	}
	if err := a.seedDefaultUsers(); err != nil {
		return nil, fmt.Errorf("seed: %w", err)
	}

	return a, nil
}

func (a *AuthDB) migrate() error {
	schema := `
	CREATE TABLE IF NOT EXISTS users (
		id TEXT PRIMARY KEY,
		username TEXT UNIQUE NOT NULL,
		hashed_password TEXT NOT NULL,
		permissions TEXT NOT NULL DEFAULT '[]',
		created_at DATETIME DEFAULT CURRENT_TIMESTAMP
	);

	CREATE TABLE IF NOT EXISTS documents (
		id TEXT PRIMARY KEY,
		user_id TEXT NOT NULL,
		filename TEXT NOT NULL,
		content_type TEXT NOT NULL,
		classification TEXT NOT NULL DEFAULT 'public',
		extracted_text TEXT DEFAULT '',
		status TEXT NOT NULL DEFAULT 'pending',
		file_path TEXT NOT NULL,
		created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
		updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
		FOREIGN KEY (user_id) REFERENCES users(id)
	);
	`
	_, err := a.db.Exec(schema)
	return err
}

func (a *AuthDB) seedDefaultUsers() error {
	users := []struct {
		username    string
		password    string
		permissions []models.Permission
	}{
		{
			username: "public_reader",
			password: "reader123",
			permissions: []models.Permission{
				models.PermPublicSearchRead,
			},
		},
		{
			username: "public_editor",
			password: "editor123",
			permissions: []models.Permission{
				models.PermPublicSearchRead,
				models.PermPublicUpload,
			},
		},
		{
			username: "private_reader",
			password: "private123",
			permissions: []models.Permission{
				models.PermPublicSearchRead,
				models.PermPrivateSearchRead,
			},
		},
		{
			username: "admin",
			password: "admin123",
			permissions: []models.Permission{
				models.PermPublicSearchRead,
				models.PermPublicUpload,
				models.PermPrivateSearchRead,
				models.PermPrivateUpload,
			},
		},
	}

	for _, u := range users {
		exists := false
		err := a.db.QueryRow("SELECT 1 FROM users WHERE username = ?", u.username).Scan(&exists)
		if err == nil {
			continue // user exists
		}

		hash, err := bcrypt.GenerateFromPassword([]byte(u.password), bcrypt.DefaultCost)
		if err != nil {
			return err
		}

		permsJSON, _ := json.Marshal(u.permissions)
		_, err = a.db.Exec(
			"INSERT INTO users (id, username, hashed_password, permissions) VALUES (?, ?, ?, ?)",
			uuid.New().String(), u.username, string(hash), string(permsJSON),
		)
		if err != nil {
			return fmt.Errorf("insert user %s: %w", u.username, err)
		}
	}
	return nil
}

func (a *AuthDB) Authenticate(username, password string) (*models.User, error) {
	var user models.User
	var permsJSON string
	var hashedPw string

	err := a.db.QueryRow(
		"SELECT id, username, hashed_password, permissions, created_at FROM users WHERE username = ?",
		username,
	).Scan(&user.ID, &user.Username, &hashedPw, &permsJSON, &user.CreatedAt)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("invalid credentials")
	}
	if err != nil {
		return nil, err
	}

	if err := bcrypt.CompareHashAndPassword([]byte(hashedPw), []byte(password)); err != nil {
		return nil, fmt.Errorf("invalid credentials")
	}

	json.Unmarshal([]byte(permsJSON), &user.Permissions)
	return &user, nil
}

func (a *AuthDB) CreateUser(req models.RegisterRequest) (*models.User, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		return nil, err
	}

	user := &models.User{
		ID:          uuid.New().String(),
		Username:    req.Username,
		Permissions: req.Permissions,
		CreatedAt:   time.Now(),
	}

	permsJSON, _ := json.Marshal(user.Permissions)
	_, err = a.db.Exec(
		"INSERT INTO users (id, username, hashed_password, permissions) VALUES (?, ?, ?, ?)",
		user.ID, user.Username, string(hash), string(permsJSON),
	)
	if err != nil {
		return nil, fmt.Errorf("create user: %w", err)
	}
	return user, nil
}

func (a *AuthDB) GetUser(userID string) (*models.User, error) {
	var user models.User
	var permsJSON string

	err := a.db.QueryRow(
		"SELECT id, username, permissions, created_at FROM users WHERE id = ?",
		userID,
	).Scan(&user.ID, &user.Username, &permsJSON, &user.CreatedAt)
	if err != nil {
		return nil, err
	}

	json.Unmarshal([]byte(permsJSON), &user.Permissions)
	return &user, nil
}

// Document operations
func (a *AuthDB) CreateDocument(doc *models.Document) error {
	_, err := a.db.Exec(
		`INSERT INTO documents (id, user_id, filename, content_type, classification, status, file_path, created_at, updated_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		doc.ID, doc.UserID, doc.Filename, doc.ContentType, doc.Classification,
		doc.Status, doc.FilePath, doc.CreatedAt, doc.UpdatedAt,
	)
	return err
}

func (a *AuthDB) UpdateDocumentStatus(docID, status, extractedText string) error {
	_, err := a.db.Exec(
		"UPDATE documents SET status = ?, extracted_text = ?, updated_at = ? WHERE id = ?",
		status, extractedText, time.Now(), docID,
	)
	return err
}

func (a *AuthDB) GetDocument(docID string) (*models.Document, error) {
	var doc models.Document
	err := a.db.QueryRow(
		`SELECT id, user_id, filename, content_type, classification, extracted_text, status, file_path, created_at, updated_at
		 FROM documents WHERE id = ?`, docID,
	).Scan(&doc.ID, &doc.UserID, &doc.Filename, &doc.ContentType, &doc.Classification,
		&doc.ExtractedText, &doc.Status, &doc.FilePath, &doc.CreatedAt, &doc.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return &doc, nil
}

func (a *AuthDB) Close() error {
	return a.db.Close()
}
