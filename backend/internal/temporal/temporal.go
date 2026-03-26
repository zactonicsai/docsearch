package temporal

import (
	"context"
	"fmt"
	"log"
	"time"

	"go.temporal.io/sdk/client"
)

const TaskQueue = "document-processing"

// RealClient wraps the Temporal SDK client
type RealClient struct {
	Client client.Client
}

// DocumentTask mirrors the Python worker's input dataclass
type DocumentTask struct {
	DocumentID     string `json:"document_id"`
	UserID         string `json:"user_id"`
	Filename       string `json:"filename"`
	FilePath       string `json:"file_path"`
	ContentType    string `json:"content_type"`
	Classification string `json:"classification"`
}

// WorkflowStatus returned when querying workflow state
type WorkflowStatus struct {
	WorkflowID string `json:"workflow_id"`
	RunID      string `json:"run_id"`
	Status     string `json:"status"`
}

// NewRealClient connects to the Temporal server with retries
func NewRealClient(hostPort string) (*RealClient, error) {
	var c client.Client
	var err error

	for attempt := 0; attempt < 30; attempt++ {
		c, err = client.Dial(client.Options{
			HostPort:  hostPort,
			Namespace: "default",
		})
		if err == nil {
			log.Println("Connected to Temporal server")
			return &RealClient{Client: c}, nil
		}
		if attempt%5 == 0 {
			log.Printf("Waiting for Temporal server at %s... (attempt %d)", hostPort, attempt+1)
		}
		time.Sleep(2 * time.Second)
	}
	return nil, fmt.Errorf("could not connect to Temporal after 60s: %w", err)
}

// StartDocumentWorkflow starts the Python worker workflow
func (rc *RealClient) StartDocumentWorkflow(ctx context.Context, task DocumentTask) (*WorkflowStatus, error) {
	workflowID := fmt.Sprintf("doc-process-%s", task.DocumentID)

	options := client.StartWorkflowOptions{
		ID:        workflowID,
		TaskQueue: TaskQueue,
	}

	run, err := rc.Client.ExecuteWorkflow(ctx, options, "DocumentProcessingWorkflow", task)
	if err != nil {
		return nil, fmt.Errorf("start workflow: %w", err)
	}

	log.Printf("Started workflow %s (run=%s) for document %s", workflowID, run.GetRunID(), task.DocumentID)

	return &WorkflowStatus{
		WorkflowID: workflowID,
		RunID:      run.GetRunID(),
		Status:     "RUNNING",
	}, nil
}

// GetWorkflowStatus queries the status of a running workflow
func (rc *RealClient) GetWorkflowStatus(ctx context.Context, workflowID string) (*WorkflowStatus, error) {
	desc, err := rc.Client.DescribeWorkflowExecution(ctx, workflowID, "")
	if err != nil {
		return nil, fmt.Errorf("describe workflow: %w", err)
	}

	status := desc.WorkflowExecutionInfo.Status.String()

	return &WorkflowStatus{
		WorkflowID: workflowID,
		RunID:      desc.WorkflowExecutionInfo.Execution.RunId,
		Status:     status,
	}, nil
}

// Close shuts down the client
func (rc *RealClient) Close() {
	if rc.Client != nil {
		rc.Client.Close()
	}
}
