package api

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"docms/internal/auth"
	"docms/internal/converter"
	"docms/internal/elasticsearch"
	"docms/internal/middleware"
	"docms/internal/models"
	"docms/internal/temporal"

	"github.com/google/uuid"
)

type Server struct {
	authDB         *auth.AuthDB
	esClient       *elasticsearch.Client
	converter      *converter.Converter
	temporalClient *temporal.RealClient
	uploadDir      string
	mux            *http.ServeMux
}

func NewServer(authDB *auth.AuthDB, esClient *elasticsearch.Client, conv *converter.Converter, tc *temporal.RealClient, uploadDir string) *Server {
	s := &Server{
		authDB:         authDB,
		esClient:       esClient,
		converter:      conv,
		temporalClient: tc,
		uploadDir:      uploadDir,
		mux:            http.NewServeMux(),
	}

	os.MkdirAll(uploadDir, 0755)
	s.setupRoutes()
	return s
}

func (s *Server) setupRoutes() {
	// Public routes
	s.mux.HandleFunc("POST /api/login", s.handleLogin)
	s.mux.HandleFunc("POST /api/register", s.handleRegister)
	s.mux.HandleFunc("GET /api/health", s.handleHealth)

	// Internal route (called by Python worker, no JWT)
	s.mux.HandleFunc("POST /internal/update-status", s.handleInternalStatusUpdate)

	// Protected routes
	protected := http.NewServeMux()
	protected.HandleFunc("POST /api/upload", s.handleUpload)
	protected.HandleFunc("POST /api/search", s.handleSearch)
	protected.HandleFunc("GET /api/me", s.handleMe)
	protected.HandleFunc("GET /api/stats", s.handleStats)

	// Temporal workflow routes (protected)
	protected.HandleFunc("POST /api/temporal/start", s.handleTemporalStart)
	protected.HandleFunc("GET /api/temporal/status", s.handleTemporalStatus)

	s.mux.Handle("/api/", middleware.AuthMiddleware(protected))
}

func (s *Server) Handler() http.Handler {
	return middleware.CORSMiddleware(s.mux)
}

// ── Auth Handlers ───────────────────────────────────────

func (s *Server) handleLogin(w http.ResponseWriter, r *http.Request) {
	var req models.LoginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}

	user, err := s.authDB.Authenticate(req.Username, req.Password)
	if err != nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid credentials"})
		return
	}

	token, err := middleware.GenerateToken(user)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "token generation failed"})
		return
	}

	writeJSON(w, http.StatusOK, models.LoginResponse{Token: token, User: *user})
}

func (s *Server) handleRegister(w http.ResponseWriter, r *http.Request) {
	var req models.RegisterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}

	if req.Username == "" || req.Password == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "username and password required"})
		return
	}

	user, err := s.authDB.CreateUser(req)
	if err != nil {
		writeJSON(w, http.StatusConflict, map[string]string{"error": fmt.Sprintf("user creation failed: %v", err)})
		return
	}

	token, err := middleware.GenerateToken(user)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "token generation failed"})
		return
	}

	writeJSON(w, http.StatusCreated, models.LoginResponse{Token: token, User: *user})
}

func (s *Server) handleMe(w http.ResponseWriter, r *http.Request) {
	user := middleware.GetUserFromContext(r)
	if user == nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "not authenticated"})
		return
	}
	writeJSON(w, http.StatusOK, user)
}

// ── Upload Handler ──────────────────────────────────────

func (s *Server) handleUpload(w http.ResponseWriter, r *http.Request) {
	user := middleware.GetUserFromContext(r)
	if user == nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "not authenticated"})
		return
	}

	classification := models.Classification(r.FormValue("classification"))
	if classification != models.ClassPublic && classification != models.ClassPrivate {
		classification = models.ClassPublic
	}

	if !user.CanUpload(classification) {
		writeJSON(w, http.StatusForbidden, map[string]string{
			"error": fmt.Sprintf("no permission to upload %s documents", classification),
		})
		return
	}

	if err := r.ParseMultipartForm(50 << 20); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "file too large or invalid form"})
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "no file provided"})
		return
	}
	defer file.Close()

	contentType := converter.DetectContentType(header.Filename)
	docID := uuid.New().String()
	savePath := filepath.Join(s.uploadDir, docID+filepath.Ext(header.Filename))

	dst, err := os.Create(savePath)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to save file"})
		return
	}
	defer dst.Close()

	if _, err := io.Copy(dst, file); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to write file"})
		return
	}

	doc := &models.Document{
		ID:             docID,
		UserID:         user.ID,
		Filename:       header.Filename,
		ContentType:    contentType,
		Classification: classification,
		Status:         "processing",
		FilePath:       savePath,
		CreatedAt:      time.Now(),
		UpdatedAt:      time.Now(),
	}

	if err := s.authDB.CreateDocument(doc); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to create document record"})
		return
	}

	// use_temporal=true → route through Temporal Python worker
	useTemporal := r.FormValue("use_temporal") == "true"

	if useTemporal && s.temporalClient != nil {
		task := temporal.DocumentTask{
			DocumentID:     docID,
			UserID:         user.ID,
			Filename:       header.Filename,
			FilePath:       savePath,
			ContentType:    contentType,
			Classification: string(classification),
		}

		wfStatus, err := s.temporalClient.StartDocumentWorkflow(r.Context(), task)
		if err != nil {
			log.Printf("Temporal workflow start failed, falling back to static: %v", err)
			go s.processDocumentStatic(doc)
		} else {
			writeJSON(w, http.StatusAccepted, map[string]interface{}{
				"document_id": docID,
				"status":      "temporal_processing",
				"workflow_id": wfStatus.WorkflowID,
				"run_id":      wfStatus.RunID,
				"message":     fmt.Sprintf("Document '%s' routed to Temporal workflow (%s)", header.Filename, classification),
			})
			return
		}
	} else {
		// Static path: Go converter stubs + direct ES index
		go s.processDocumentStatic(doc)
	}

	writeJSON(w, http.StatusAccepted, models.UploadResponse{
		DocumentID: docID,
		Status:     "processing",
		Message:    fmt.Sprintf("Document '%s' uploaded via static pipeline (%s)", header.Filename, classification),
	})
}

func (s *Server) processDocumentStatic(doc *models.Document) {
	log.Printf("[Static] Processing document %s (%s) - classification: %s", doc.ID, doc.ContentType, doc.Classification)

	extractedText, err := s.converter.Convert(doc)
	if err != nil {
		log.Printf("Error converting document %s: %v", doc.ID, err)
		s.authDB.UpdateDocumentStatus(doc.ID, "failed", "")
		return
	}

	if err := s.authDB.UpdateDocumentStatus(doc.ID, "completed", extractedText); err != nil {
		log.Printf("Error updating document %s status: %v", doc.ID, err)
		return
	}

	esDoc := models.ElasticDocument{
		DocID:          doc.ID,
		UserID:         doc.UserID,
		Filename:       doc.Filename,
		Classification: doc.Classification,
		Content:        extractedText,
		ContentType:    doc.ContentType,
		IndexedAt:      time.Now(),
	}

	if err := s.esClient.IndexDocument(esDoc); err != nil {
		log.Printf("Error indexing document %s: %v", doc.ID, err)
		s.authDB.UpdateDocumentStatus(doc.ID, "index_failed", extractedText)
		return
	}

	log.Printf("[Static] Document %s processed and indexed (classification: %s)", doc.ID, doc.Classification)
}

// ── Temporal Workflow Handlers ──────────────────────────

func (s *Server) handleTemporalStart(w http.ResponseWriter, r *http.Request) {
	user := middleware.GetUserFromContext(r)
	if user == nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "not authenticated"})
		return
	}

	var req struct {
		DocumentID     string `json:"document_id"`
		Classification string `json:"classification"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}

	if s.temporalClient == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Temporal not connected"})
		return
	}

	doc, err := s.authDB.GetDocument(req.DocumentID)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "document not found"})
		return
	}

	classification := models.Classification(req.Classification)
	if classification == "" {
		classification = doc.Classification
	}
	if !user.CanUpload(classification) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "insufficient permissions"})
		return
	}

	task := temporal.DocumentTask{
		DocumentID:     doc.ID,
		UserID:         doc.UserID,
		Filename:       doc.Filename,
		FilePath:       doc.FilePath,
		ContentType:    doc.ContentType,
		Classification: string(classification),
	}

	wfStatus, err := s.temporalClient.StartDocumentWorkflow(r.Context(), task)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": fmt.Sprintf("workflow start failed: %v", err)})
		return
	}

	s.authDB.UpdateDocumentStatus(doc.ID, "temporal_processing", "")

	writeJSON(w, http.StatusAccepted, wfStatus)
}

func (s *Server) handleTemporalStatus(w http.ResponseWriter, r *http.Request) {
	user := middleware.GetUserFromContext(r)
	if user == nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "not authenticated"})
		return
	}

	workflowID := r.URL.Query().Get("workflow_id")
	if workflowID == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "workflow_id required"})
		return
	}

	if s.temporalClient == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Temporal not connected"})
		return
	}

	status, err := s.temporalClient.GetWorkflowStatus(r.Context(), workflowID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": fmt.Sprintf("status query failed: %v", err)})
		return
	}

	writeJSON(w, http.StatusOK, status)
}

// ── Internal Status Update (called by Python worker) ────

func (s *Server) handleInternalStatusUpdate(w http.ResponseWriter, r *http.Request) {
	var req struct {
		DocumentID    string `json:"document_id"`
		Status        string `json:"status"`
		ExtractedText string `json:"extracted_text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
		return
	}

	if err := s.authDB.UpdateDocumentStatus(req.DocumentID, req.Status, req.ExtractedText); err != nil {
		log.Printf("Internal status update failed for %s: %v", req.DocumentID, err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "update failed"})
		return
	}

	log.Printf("[Internal] Document %s status updated to '%s'", req.DocumentID, req.Status)
	writeJSON(w, http.StatusOK, map[string]string{"ok": "true"})
}

// ── Search Handler ──────────────────────────────────────

func (s *Server) handleSearch(w http.ResponseWriter, r *http.Request) {
	user := middleware.GetUserFromContext(r)
	if user == nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "not authenticated"})
		return
	}

	var req models.SearchRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}

	if req.Query == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "query required"})
		return
	}

	classifications := user.GetSearchableClassifications()
	if len(classifications) == 0 {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "no search permissions"})
		return
	}

	log.Printf("User %s searching for %q with classifications: %v", user.Username, req.Query, classifications)

	result, err := s.esClient.Search(r.Context(), req.Query, classifications, req.Page, req.Size)
	if err != nil {
		log.Printf("Search error: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "search failed"})
		return
	}

	writeJSON(w, http.StatusOK, result)
}

// ── Stats / Health ──────────────────────────────────────

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	docCount, _ := s.esClient.GetDocumentCount()
	temporalStatus := "not_configured"
	if s.temporalClient != nil {
		temporalStatus = "connected"
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"status":         "healthy",
		"elasticsearch":  "connected",
		"temporal":       temporalStatus,
		"document_count": docCount,
		"timestamp":      time.Now().Format(time.RFC3339),
	})
}

func (s *Server) handleStats(w http.ResponseWriter, r *http.Request) {
	docCount, _ := s.esClient.GetDocumentCount()
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"total_indexed":   docCount,
		"supported_types": s.converter.GetSupportedTypes(),
	})
}

func writeJSON(w http.ResponseWriter, code int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(data)
}
