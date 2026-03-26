package main

import (
	"log"
	"net/http"
	"os"

	"docms/internal/api"
	"docms/internal/auth"
	"docms/internal/converter"
	"docms/internal/elasticsearch"
	"docms/internal/temporal"
)

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	esURL := getEnv("ELASTICSEARCH_URL", "http://localhost:9200")
	port := getEnv("SERVER_PORT", "8080")
	dbPath := getEnv("AUTH_DB_PATH", "/data/auth.db")
	uploadDir := getEnv("UPLOAD_DIR", "/data/uploads")
	temporalHost := getEnv("TEMPORAL_HOST", "temporal:7233")

	log.Println("═══════════════════════════════════════════")
	log.Println("  DocMS - Document Management System")
	log.Println("═══════════════════════════════════════════")

	// Initialize auth database (SQLite)
	log.Println("Initializing auth database...")
	authDB, err := auth.NewAuthDB(dbPath)
	if err != nil {
		log.Fatalf("Failed to initialize auth DB: %v", err)
	}
	defer authDB.Close()
	log.Println("Auth database ready with seed users")

	// Initialize Elasticsearch client
	log.Println("Connecting to Elasticsearch...")
	esClient, err := elasticsearch.NewClient(esURL)
	if err != nil {
		log.Fatalf("Failed to connect to Elasticsearch: %v", err)
	}
	log.Println("Elasticsearch connected and index ready")

	// Initialize document converter (static path stubs)
	log.Println("Initializing document converter workers...")
	conv := converter.NewConverter()

	// Initialize real Temporal client
	log.Printf("Connecting to Temporal at %s...", temporalHost)
	var temporalClient *temporal.RealClient
	temporalClient, err = temporal.NewRealClient(temporalHost)
	if err != nil {
		log.Printf("WARNING: Temporal connection failed: %v", err)
		log.Println("Static processing will be used. Temporal workflows disabled.")
		temporalClient = nil
	} else {
		defer temporalClient.Close()
		log.Println("Temporal connected — workflows enabled")
	}

	// Create and start API server
	server := api.NewServer(authDB, esClient, conv, temporalClient, uploadDir)

	log.Printf("Server starting on :%s", port)
	log.Println("═══════════════════════════════════════════")
	log.Println("Default users:")
	log.Println("  public_reader / reader123    → public search")
	log.Println("  public_editor / editor123    → public search + upload")
	log.Println("  private_reader / private123  → public + private search")
	log.Println("  admin / admin123             → full access")
	log.Println("═══════════════════════════════════════════")
	log.Println("Upload modes:")
	log.Println("  Static:   POST /api/upload (default)")
	log.Println("  Temporal: POST /api/upload?use_temporal=true")
	log.Println("═══════════════════════════════════════════")

	if err := http.ListenAndServe(":"+port, server.Handler()); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
