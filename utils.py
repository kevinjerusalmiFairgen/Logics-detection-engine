"""
Shared utilities for the Survey Digitization Pipeline.

Contains the Manus API client and common helper functions.
"""

import os
import json
import time
import requests
from typing import Optional, Callable, Dict, List, Any
from dataclasses import dataclass
from pathlib import Path


# =============================================================================
# Manus API Client
# =============================================================================

@dataclass
class FileUploadResult:
    """Result of a file upload operation"""
    file_id: str
    filename: str
    status: str


@dataclass
class TaskResult:
    """Result of task creation"""
    task_id: str
    task_title: str
    task_url: str
    share_url: Optional[str] = None


@dataclass
class OutputFile:
    """An output file from a completed task"""
    filename: str
    url: str
    mime_type: str


class ManusAPIClient:
    """Client for interacting with the Manus API"""
    
    BASE_URL = "https://api.manus.ai/v1"
    
    def __init__(self, api_key: str = None):
        """
        Initialize the Manus API client.
        
        Args:
            api_key: Your Manus API key. Uses MANUS_API_KEY env var if not provided.
        """
        self.api_key = api_key or os.getenv("MANUS_API_KEY")
        if not self.api_key:
            raise ValueError("MANUS_API_KEY not found. Set via argument or environment.")
        
        self.headers = {
            "API_KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make an API request"""
        url = f"{self.BASE_URL}{endpoint}"
        response = requests.request(method, url, headers=self.headers, **kwargs)
        
        if not response.ok:
            error_msg = f"API request failed: {response.status_code}"
            try:
                error_detail = response.json()
                error_msg += f" - {json.dumps(error_detail)}"
            except:
                error_msg += f" - {response.text}"
            raise Exception(error_msg)
        
        return response.json()
    
    def create_file_record(self, filename: str) -> dict:
        """Create a file record and get presigned upload URL."""
        data = {"filename": filename}
        return self._request("POST", "/files", json=data)
    
    def upload_file_to_s3(self, upload_url: str, file_path: str) -> bool:
        """Upload file content to S3 using presigned URL."""
        with open(file_path, "rb") as f:
            file_content = f.read()
        
        if file_path.lower().endswith(".pdf"):
            content_type = "application/pdf"
        elif file_path.lower().endswith(".sav"):
            content_type = "application/x-spss-sav"
        else:
            content_type = "application/octet-stream"
        
        response = requests.put(
            upload_url,
            data=file_content,
            headers={"Content-Type": content_type}
        )
        
        if not response.ok:
            raise Exception(f"S3 upload failed: {response.status_code} - {response.text}")
        
        return True
    
    def upload_file(self, file_path: str, custom_filename: str = None) -> FileUploadResult:
        """Upload a file to Manus (creates record + uploads to S3)."""
        filename = custom_filename or os.path.basename(file_path)
        file_record = self.create_file_record(filename)
        file_id = file_record["id"]
        upload_url = file_record["upload_url"]
        self.upload_file_to_s3(upload_url, file_path)
        
        return FileUploadResult(
            file_id=file_id,
            filename=filename,
            status="uploaded"
        )
    
    def upload_json(self, data: any, filename: str) -> FileUploadResult:
        """Upload JSON data as a file with specific filename."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f, indent=2)
            temp_path = f.name
        
        result = self.upload_file(temp_path, custom_filename=filename)
        os.unlink(temp_path)
        return result
    
    def create_task(
        self,
        prompt: str,
        attachments: Optional[list[dict]] = None,
        agent_profile: str = "manus-1.6",
        task_mode: str = "agent",
        create_shareable_link: bool = True
    ) -> TaskResult:
        """Create a new task."""
        data = {
            "prompt": prompt,
            "agentProfile": agent_profile,
            "taskMode": task_mode,
            "createShareableLink": create_shareable_link
        }
        
        if attachments:
            data["attachments"] = attachments
        
        result = self._request("POST", "/tasks", json=data)
        
        return TaskResult(
            task_id=result.get("task_id"),
            task_title=result.get("task_title"),
            task_url=result.get("task_url"),
            share_url=result.get("share_url")
        )
    
    def get_task(self, task_id: str) -> dict:
        """Get task details by ID."""
        return self._request("GET", f"/tasks/{task_id}")
    
    def poll_task_completion(
        self,
        task_id: str,
        poll_interval: int = 10,
        max_wait: int = 3600,
        show_thinking: bool = False,
        on_thinking: Optional[Callable[[str], None]] = None,
        initial_delay: int = 3
    ) -> dict:
        """Poll for task completion with optional thinking output."""
        if initial_delay > 0:
            time.sleep(initial_delay)
        
        start_time = time.time()
        last_message_count = 0
        
        while time.time() - start_time < max_wait:
            task = self.get_task(task_id)
            status = task.get("status", "unknown")
            
            if show_thinking or on_thinking:
                output = task.get("output", [])
                if len(output) > last_message_count:
                    for msg in output[last_message_count:]:
                        if msg.get("role") == "assistant":
                            content = msg.get("content", [])
                            for item in content:
                                if item.get("type") == "output_text":
                                    text = item.get("text", "")
                                    if text:
                                        if on_thinking:
                                            on_thinking(text)
                                        elif show_thinking:
                                            print(f"\n{'='*60}")
                                            print("MANUS THINKING:")
                                            print('='*60)
                                            print(text)
                    last_message_count = len(output)
            
            if status in ["completed", "failed", "cancelled"]:
                return task
            
            elapsed = int(time.time() - start_time)
            print(f"  [{elapsed}s] Task status: {status}...")
            time.sleep(poll_interval)
        
        raise TimeoutError(f"Task {task_id} did not complete within {max_wait} seconds")
    
    def extract_output_files(self, task: dict) -> list[OutputFile]:
        """Extract output file information from a completed task."""
        files = []
        output = task.get("output", [])
        
        for msg in output:
            content = msg.get("content", [])
            for item in content:
                if item.get("type") == "output_file":
                    files.append(OutputFile(
                        filename=item.get("fileName", "unknown"),
                        url=item.get("fileUrl", ""),
                        mime_type=item.get("mimeType", "application/octet-stream")
                    ))
        
        return files


# =============================================================================
# JSON Extraction Helpers
# =============================================================================

def extract_json_from_task(client: ManusAPIClient, task: Dict) -> Any:
    """Extract JSON result from completed task output."""
    output = task.get("output", [])
    
    # First check for output files - they're more reliable
    # Prioritize our specific expected output files
    expected_outputs = [
        "pdf_structure.json",
        "mapping_output.json", 
        "resolution_output.json",
        "logic_output.json"
    ]
    
    files = client.extract_output_files(task)
    
    # First pass: look for specifically named files
    for expected_name in expected_outputs:
        for file in files:
            if file.filename == expected_name:
                print(f"  [INFO] Found expected output file: {expected_name}")
                response = requests.get(file.url)
                if response.ok:
                    return response.json()
    
    # Second pass: any JSON file
    for file in files:
        if file.filename.endswith(".json"):
            print(f"  [INFO] Found JSON output file: {file.filename}")
            response = requests.get(file.url)
            if response.ok:
                return response.json()
    
    # Collect ALL content from assistant messages
    all_text = []
    all_content_types = set()
    for msg in output:
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            for item in content:
                item_type = item.get("type", "")
                all_content_types.add(item_type)
                # Check multiple possible text fields
                text = item.get("text", "") or item.get("content", "") or item.get("value", "")
                if text:
                    all_text.append(text)
    
    # Debug output
    print(f"  [DEBUG] Content types found: {all_content_types}")
    print(f"  [DEBUG] Found {len(all_text)} text blocks, total {sum(len(t) for t in all_text)} chars")
    
    # Try to find JSON in all collected text (reversed - most recent first)
    for text in reversed(all_text):
        if not text:
            continue
        try:
            # Try to find JSON object first (more common for our outputs)
            json_start = text.find("{")
            if json_start >= 0:
                # Find matching closing brace
                bracket_count = 0
                for i, char in enumerate(text[json_start:], json_start):
                    if char == "{":
                        bracket_count += 1
                    elif char == "}":
                        bracket_count -= 1
                        if bracket_count == 0:
                            json_str = text[json_start:i+1]
                            return json.loads(json_str)
            
            # Try to find JSON array
            array_start = text.find("[")
            if array_start >= 0:
                bracket_count = 0
                for i, char in enumerate(text[array_start:], array_start):
                    if char == "[":
                        bracket_count += 1
                    elif char == "]":
                        bracket_count -= 1
                        if bracket_count == 0:
                            json_str = text[array_start:i+1]
                            return json.loads(json_str)
        except json.JSONDecodeError:
            continue
    
    # Print more debug info
    for i, t in enumerate(all_text[-3:]):  # Show last 3
        print(f"  [DEBUG] Text block {i}: {t[:500]}...")
    
    # Try fetching raw task data for debugging
    print(f"  [DEBUG] Raw output message count: {len(output)}")
    if output:
        last_msg = output[-1]
        print(f"  [DEBUG] Last message role: {last_msg.get('role')}")
        print(f"  [DEBUG] Last message content count: {len(last_msg.get('content', []))}")
    
    raise Exception("Could not extract JSON result from task output")


# =============================================================================
# Variable Helpers
# =============================================================================

def flatten_vars(vars_field) -> List[str]:
    """Flatten grid vars (list of lists) into a single list."""
    if not vars_field:
        return []
    
    if isinstance(vars_field, list) and vars_field and isinstance(vars_field[0], list):
        flat = []
        for row in vars_field:
            if isinstance(row, list):
                flat.extend(row)
            else:
                flat.append(row)
        return flat
    
    return vars_field if isinstance(vars_field, list) else [vars_field]


def get_all_question_vars(questions: List[Dict]) -> List[str]:
    """Get all variable names from all questions (flattening grids)."""
    all_vars = []
    for q in questions:
        all_vars.extend(flatten_vars(q.get("vars", [])))
    return all_vars
