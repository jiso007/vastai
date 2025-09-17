#!/usr/bin/env python3
"""
ComfyUI API Control via SSH
Programmatically modify and execute ComfyUI workflows on a remote Vast.ai instance.
"""

import paramiko
import json
import os
import sys
import time
import uuid
from typing import Dict, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

class ComfyUIController:
    def __init__(self, instance_id: str, ssh_host: str, ssh_port: int, ssh_key_path: Optional[str] = None):
        """
        Initialize ComfyUI controller for a Vast.ai instance.
        
        Args:
            instance_id: The Vast.ai instance ID
            ssh_host: SSH host (e.g., ssh5.vast.ai)
            ssh_port: SSH port number
            ssh_key_path: Path to SSH private key (auto-detects if not provided)
        """
        self.instance_id = instance_id
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        
        # Auto-detect SSH key if not provided
        if ssh_key_path:
            self.ssh_key_path = ssh_key_path
        else:
            possible_keys = [
                "~/.ssh/id_ed25519_vastai",
                "~/.ssh/id_ed25519",
                "~/.ssh/id_rsa"
            ]
            
            for key_path in possible_keys:
                full_path = os.path.expanduser(key_path)
                if os.path.exists(full_path):
                    self.ssh_key_path = full_path
                    break
            else:
                raise ValueError("No SSH key found. Please provide ssh_key_path.")
        
        self.ssh_client = None
        self.comfyui_url = "http://127.0.0.1:8188"
        
    def connect(self):
        """Establish SSH connection to the instance."""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            key = paramiko.Ed25519Key.from_private_key_file(self.ssh_key_path)
            
            print(f"🔗 Connecting to {self.ssh_host}:{self.ssh_port}...")
            self.ssh_client.connect(
                hostname=self.ssh_host,
                port=self.ssh_port,
                username='root',
                pkey=key,
                timeout=30
            )
            print("✅ SSH connection established")
            return True
            
        except Exception as e:
            print(f"❌ SSH connection failed: {e}")
            return False
    
    def disconnect(self):
        """Close SSH connection."""
        if self.ssh_client:
            self.ssh_client.close()
            print("🔌 SSH connection closed")
    
    def upload_image(self, local_image_path: str, remote_filename: Optional[str] = None) -> str:
        """
        Upload an image to the ComfyUI input directory.
        
        Args:
            local_image_path: Path to the local image file
            remote_filename: Optional custom filename on remote (uses local filename if not provided)
            
        Returns:
            The filename used on the remote instance
        """
        if not os.path.exists(local_image_path):
            raise FileNotFoundError(f"Local image not found: {local_image_path}")
        
        if not remote_filename:
            remote_filename = os.path.basename(local_image_path)
        
        # Check common ComfyUI installation paths
        possible_paths = [
            f"/workspace/ComfyUI/input/{remote_filename}",
            f"/root/ComfyUI/input/{remote_filename}",
            f"/ComfyUI/input/{remote_filename}"
        ]
        
        # Find the correct path by checking which directory exists
        remote_path = None
        for path in ["/workspace/ComfyUI/input", "/root/ComfyUI/input", "/ComfyUI/input"]:
            stdin, stdout, stderr = self.ssh_client.exec_command(f"test -d {path} && echo 'exists'")
            if stdout.read().decode().strip() == 'exists':
                remote_path = f"{path}/{remote_filename}"
                break
        
        if not remote_path:
            # Create the workspace directory if none exist
            self.ssh_client.exec_command("mkdir -p /workspace/ComfyUI/input")
            remote_path = f"/workspace/ComfyUI/input/{remote_filename}"
        
        print(f"📤 Uploading {local_image_path} to {remote_path}...")
        
        sftp = self.ssh_client.open_sftp()
        try:
            sftp.put(local_image_path, remote_path)
            print(f"✅ Image uploaded: {remote_filename}")
            return remote_filename
        finally:
            sftp.close()
    
    def execute_command(self, command: str) -> Tuple[str, str, int]:
        """Execute a command via SSH and return stdout, stderr, and exit code."""
        stdin, stdout, stderr = self.ssh_client.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        return stdout.read().decode(), stderr.read().decode(), exit_code
    
    def get_latest_workflow(self) -> Dict:
        """Fetch the latest workflow from ComfyUI history."""
        print("📥 Fetching latest workflow from ComfyUI...")
        
        cmd = f'curl -s -X GET "{self.comfyui_url}/history"'
        stdout, stderr, exit_code = self.execute_command(cmd)
        
        if exit_code != 0:
            raise RuntimeError(f"Failed to fetch history: {stderr}")
        
        history = json.loads(stdout)
        if not history:
            raise RuntimeError("No workflow history found. Please run a workflow in ComfyUI first.")
        
        # Get the most recent prompt ID
        latest_prompt_id = list(history.keys())[0]
        workflow_data = history[latest_prompt_id]["prompt"][2]
        
        print(f"✅ Found latest workflow (ID: {latest_prompt_id})")
        return workflow_data
    
    def modify_workflow(self, workflow: Dict, image_filename: str, prompt_text: str, 
                       prompt_node_id: str = "6", image_node_id: str = "62") -> Dict:
        """
        Modify workflow with new image and prompt.
        
        Args:
            workflow: The workflow dictionary
            image_filename: Filename of the image in ComfyUI/input/
            prompt_text: The new prompt text
            prompt_node_id: Node ID for the positive prompt (default: "6")
            image_node_id: Node ID for the image loader (default: "62")
            
        Returns:
            Modified workflow dictionary
        """
        print(f"🔧 Modifying workflow with prompt: '{prompt_text}' and image: '{image_filename}'")
        
        # Update positive prompt
        if prompt_node_id in workflow:
            old_prompt = workflow[prompt_node_id]["inputs"].get("text", "")
            workflow[prompt_node_id]["inputs"]["text"] = prompt_text
            print(f"✅ Updated prompt in node {prompt_node_id}")
            print(f"   Old: '{old_prompt}'")
            print(f"   New: '{prompt_text}'")
        else:
            print(f"⚠️ Warning: Prompt node {prompt_node_id} not found")
            print(f"   Available nodes: {list(workflow.keys())}")
        
        # Update image
        if image_node_id in workflow:
            old_image = workflow[image_node_id]["inputs"].get("image", "")
            workflow[image_node_id]["inputs"]["image"] = image_filename
            print(f"✅ Updated image in node {image_node_id}")
            print(f"   Old: '{old_image}'")
            print(f"   New: '{image_filename}'")
        else:
            print(f"⚠️ Warning: Image node {image_node_id} not found")
            print(f"   Available nodes: {list(workflow.keys())}")
        
        return workflow
    
    def get_node_info(self, node_type: str) -> Dict:
        """Get node input configuration from ComfyUI API."""
        try:
            cmd = f'curl -s http://127.0.0.1:8188/object_info/{node_type}'
            stdout, stderr, exit_code = self.execute_command(cmd)
            
            if exit_code == 0:
                return json.loads(stdout)
            return {}
        except:
            return {}
    
    def map_widget_values_to_inputs(self, node_type: str, widget_values: list, inputs_config: list) -> Dict:
        """
        Dynamically map widget values to input names by analyzing the mismatch.
        
        Args:
            node_type: The type of the node
            widget_values: List of widget values from the workflow
            inputs_config: List of input definitions from the workflow node
            
        Returns:
            Dictionary mapping input names to values
        """
        api_inputs = {}
        
        # Get only the widget inputs (those without links)
        widget_inputs = [input_def for input_def in inputs_config 
                        if input_def.get('widget') is not None and input_def.get('link') is None]
        
        # If we have more widget_values than widget_inputs, there might be extra/unused values
        if len(widget_values) > len(widget_inputs):
            print(f"⚠️ Node {node_type}: {len(widget_values)} widget values but only {len(widget_inputs)} widget inputs")
            print(f"   Widget values: {widget_values}")
            print(f"   Widget inputs: {[inp['name'] for inp in widget_inputs]}")
            
            # Try to intelligently map by skipping obvious non-input values
            widget_index = 0
            for input_def in widget_inputs:
                input_name = input_def['name']
                
                # For each expected input, try to find the best matching value
                if widget_index < len(widget_values):
                    value = widget_values[widget_index]
                    
                    # If this value seems wrong for this input type, try next value
                    if self._value_seems_wrong_for_input(input_name, value, widget_values, widget_index):
                        widget_index += 1
                        if widget_index < len(widget_values):
                            value = widget_values[widget_index]
                    
                    api_inputs[input_name] = value
                    widget_index += 1
        else:
            # Simple 1:1 mapping when counts match
            for i, input_def in enumerate(widget_inputs):
                if i < len(widget_values):
                    api_inputs[input_def['name']] = widget_values[i]
        
        return api_inputs
    
    def _value_seems_wrong_for_input(self, input_name: str, value, all_values: list, current_index: int) -> bool:
        """Check if a value seems wrong for a given input and we should skip it."""
        
        # Common patterns where widget_values has extra items
        if input_name == "steps" and isinstance(value, str) and value in ["randomize", "fixed"]:
            return True
        
        if input_name == "start_at_step" and isinstance(value, str) and value in ["beta", "euler", "simple"]:
            return True
            
        if input_name == "sampler_name" and isinstance(value, (int, float)):
            return True
            
        if input_name == "return_with_leftover_noise" and isinstance(value, (int, float)) and value > 1:
            return True
        
        return False

    def load_workflow_from_file(self, workflow_path: str) -> Dict:
        """
        Load a workflow JSON file from the remote instance and convert to API format.
        
        Args:
            workflow_path: Path to the workflow JSON file on the remote instance
            
        Returns:
            Workflow dictionary in API prompt format
        """
        print(f"📥 Loading workflow from {workflow_path}...")
        
        cmd = f"cat {workflow_path}"
        stdout, stderr, exit_code = self.execute_command(cmd)
        
        if exit_code != 0:
            raise RuntimeError(f"Failed to read workflow file: {stderr}")
        
        try:
            workflow_data = json.loads(stdout)
            
            # Convert ComfyUI workflow format to API prompt format
            if 'nodes' in workflow_data:
                print("🔄 Converting workflow format to API format...")
                prompt = {}
                
                for node in workflow_data['nodes']:
                    node_id = str(node['id'])
                    node_type = node['type']
                    
                    # Start with empty inputs
                    api_inputs = {}
                    
                    # Handle node connections first
                    if 'inputs' in node and isinstance(node['inputs'], list):
                        for input_def in node['inputs']:
                            if input_def.get('link') is not None:
                                link_id = input_def['link']
                                input_name = input_def['name']
                                
                                # Find the source node for this link
                                for link in workflow_data.get('links', []):
                                    if link[0] == link_id:  # link format: [id, from_node, from_slot, to_node, to_slot, type]
                                        source_node_id = link[1]
                                        source_slot = link[2]
                                        api_inputs[input_name] = [str(source_node_id), source_slot]
                                        break
                    
                    # Handle widget values dynamically
                    if 'widgets_values' in node and node['widgets_values'] and 'inputs' in node:
                        widget_inputs = self.map_widget_values_to_inputs(
                            node_type, 
                            node['widgets_values'], 
                            node['inputs']
                        )
                        api_inputs.update(widget_inputs)
                    
                    prompt[node_id] = {
                        "class_type": node_type,
                        "inputs": api_inputs
                    }
                
                print("✅ Workflow loaded and converted to API format")
                return prompt
            else:
                # Already in prompt format
                print("✅ Workflow loaded (already in API format)")
                return workflow_data
                
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in workflow file: {e}")
    
    def queue_prompt(self, workflow: Dict) -> str:
        """
        Queue a workflow for execution.
        
        Args:
            workflow: The workflow dictionary to execute
            
        Returns:
            The prompt ID of the queued job
        """
        print("🚀 Queueing workflow...")
        
        client_id = str(uuid.uuid4())
        payload = {
            "prompt": workflow,
            "client_id": client_id
        }
        
        # Create a temporary file with the payload
        temp_payload_file = f"/tmp/comfyui_payload_{client_id}.json"
        
        # Write payload to temporary file
        cmd = f"echo '{json.dumps(payload)}' > {temp_payload_file}"
        self.execute_command(cmd)
        
        # Queue the prompt
        cmd = f'curl -s -X POST -H "Content-Type: application/json" -d @{temp_payload_file} "{self.comfyui_url}/prompt"'
        stdout, stderr, exit_code = self.execute_command(cmd)
        
        # Clean up temporary file
        self.execute_command(f"rm -f {temp_payload_file}")
        
        if exit_code != 0:
            raise RuntimeError(f"Failed to queue prompt: {stderr}")
        
        response = json.loads(stdout)
        prompt_id = response.get("prompt_id")
        
        if not prompt_id:
            raise RuntimeError(f"Failed to get prompt ID: {response}")
        
        print(f"✅ Job queued! Prompt ID: {prompt_id}")
        return prompt_id
    
    def run_workflow(self, local_image_path: str, prompt_text: str, 
                    prompt_node_id: str = "6", image_node_id: str = "62") -> str:
        """
        Complete workflow: upload image, modify workflow, and queue execution.
        
        Args:
            local_image_path: Path to the local image file
            prompt_text: The prompt text to use
            prompt_node_id: Node ID for the positive prompt (default: "6")
            image_node_id: Node ID for the image loader (default: "62")
            
        Returns:
            The prompt ID of the queued job
        """
        print("=" * 50)
        print("🎨 ComfyUI Workflow Execution")
        print("=" * 50)
        print(f"📸 Image: {local_image_path}")
        print(f"💭 Prompt: {prompt_text}")
        print("=" * 50)
        
        # Upload image
        image_filename = self.upload_image(local_image_path)
        
        # Get latest workflow
        workflow = self.get_latest_workflow()
        
        # Modify workflow
        modified_workflow = self.modify_workflow(
            workflow, 
            image_filename, 
            prompt_text,
            prompt_node_id,
            image_node_id
        )
        
        # Queue execution
        prompt_id = self.queue_prompt(modified_workflow)
        
        print("=" * 50)
        print("🎉 Workflow submitted successfully!")
        print(f"📁 Output will appear in ComfyUI/output/")
        print("=" * 50)
        
        return prompt_id
    
    def get_queue_status(self) -> Dict:
        """Get current queue status from ComfyUI."""
        cmd = f'curl -s -X GET "{self.comfyui_url}/queue"'
        stdout, stderr, exit_code = self.execute_command(cmd)
        
        if exit_code != 0:
            raise RuntimeError(f"Failed to get queue status: {stderr}")
        
        return json.loads(stdout)
    
    def get_history_item(self, prompt_id: str) -> Dict:
        """Get a specific item from history by prompt ID."""
        cmd = f'curl -s -X GET "{self.comfyui_url}/history/{prompt_id}"'
        stdout, stderr, exit_code = self.execute_command(cmd)
        
        if exit_code != 0:
            return {}
        
        try:
            return json.loads(stdout)
        except:
            return {}
    
    def audit_workflow_changes(self, original_workflow: Dict, modified_workflow: Dict, 
                              image_filename: str, prompt_text: str):
        """Show a detailed audit of what changed in the workflow."""
        print("\n" + "=" * 60)
        print("🔍 WORKFLOW AUDIT")
        print("=" * 60)
        
        changes_found = False
        
        # Check each node for changes
        for node_id, modified_node in modified_workflow.items():
            if node_id in original_workflow:
                orig_inputs = original_workflow[node_id].get('inputs', {})
                mod_inputs = modified_node.get('inputs', {})
                
                # Check for input changes
                for input_name, new_value in mod_inputs.items():
                    old_value = orig_inputs.get(input_name)
                    
                    if old_value != new_value:
                        changes_found = True
                        node_type = modified_node.get('class_type', 'Unknown')
                        print(f"📝 Node {node_id} ({node_type}) - {input_name}:")
                        print(f"   Old: {old_value}")
                        print(f"   New: {new_value}")
                        
                        # Highlight our specific changes
                        if input_name == "text" and new_value == prompt_text:
                            print("   ✅ This is your custom prompt!")
                        elif input_name == "image" and new_value == image_filename:
                            print("   ✅ This is your uploaded image!")
                        print()
        
        if not changes_found:
            print("⚠️ No changes detected in workflow")
        
        print("=" * 60)
    
    def save_modified_workflow(self, workflow: Dict, output_path: str):
        """Save the modified workflow to a file for inspection."""
        cmd = f"echo '{json.dumps(workflow, indent=2)}' > {output_path}"
        self.execute_command(cmd)
        print(f"💾 Modified workflow saved to: {output_path}")
    
    def convert_api_to_workflow_format(self, api_workflow: Dict, original_workflow_data: Dict, 
                                       image_filename: str, prompt_text: str) -> Dict:
        """
        Convert API format back to workflow format for ComfyUI UI compatibility.
        
        Args:
            api_workflow: The API format workflow
            original_workflow_data: The original workflow file data (with nodes, links, etc.)
            image_filename: The new image filename
            prompt_text: The new prompt text
            
        Returns:
            Workflow in ComfyUI UI format
        """
        # Start with the original workflow structure
        ui_workflow = original_workflow_data.copy()
        
        # Update the specific nodes with our changes
        if 'nodes' in ui_workflow:
            for node in ui_workflow['nodes']:
                node_id = str(node['id'])
                
                # Update prompt node (node 6)
                if node_id == "6" and node.get('type') == 'CLIPTextEncode':
                    if 'widgets_values' in node:
                        node['widgets_values'][0] = prompt_text
                        print(f"✅ Updated UI workflow node {node_id} prompt: '{prompt_text}'")
                
                # Update image node (node 62) 
                elif node_id == "62" and node.get('type') == 'LoadImage':
                    if 'widgets_values' in node:
                        node['widgets_values'][0] = image_filename
                        print(f"✅ Updated UI workflow node {node_id} image: '{image_filename}'")
        
        return ui_workflow
    
    def save_ui_compatible_workflow(self, api_workflow: Dict, original_workflow_data: Dict,
                                   image_filename: str, prompt_text: str, output_path: str):
        """Save a ComfyUI UI-compatible version of the modified workflow."""
        ui_workflow = self.convert_api_to_workflow_format(
            api_workflow, original_workflow_data, image_filename, prompt_text
        )
        
        cmd = f"echo '{json.dumps(ui_workflow, indent=2)}' > {output_path}"
        self.execute_command(cmd)
        print(f"💾 UI-compatible workflow saved to: {output_path}")
        print(f"   You can drag this file into ComfyUI web interface!")
    
    def run_workflow_from_file(self, workflow_file_path: str, local_image_path: str, 
                              prompt_text: str, prompt_node_id: str = "6", 
                              image_node_id: str = "62") -> str:
        """
        Load a workflow from a JSON file and execute it with custom image and prompt.
        
        Args:
            workflow_file_path: Path to the workflow JSON file on the remote instance
            local_image_path: Path to the local image file
            prompt_text: The prompt text to use
            prompt_node_id: Node ID for the positive prompt (default: "6")
            image_node_id: Node ID for the image loader (default: "62")
            
        Returns:
            The prompt ID of the queued job
        """
        print("=" * 50)
        print("🎨 ComfyUI Workflow Execution (from file)")
        print("=" * 50)
        print(f"📄 Workflow: {workflow_file_path}")
        print(f"📸 Image: {local_image_path}")
        print(f"💭 Prompt: {prompt_text}")
        print("=" * 50)
        
        # Upload image
        image_filename = self.upload_image(local_image_path)
        
        # Load the original workflow file data (for UI format conversion)
        cmd = f"cat {workflow_file_path}"
        stdout, stderr, exit_code = self.execute_command(cmd)
        if exit_code != 0:
            raise RuntimeError(f"Failed to read workflow file: {stderr}")
        original_workflow_data = json.loads(stdout)
        
        # Load workflow from file (converted to API format)
        original_workflow = self.load_workflow_from_file(workflow_file_path)
        
        # Modify workflow
        modified_workflow = self.modify_workflow(
            original_workflow, 
            image_filename, 
            prompt_text,
            prompt_node_id,
            image_node_id
        )
        
        # Show audit of changes
        self.audit_workflow_changes(original_workflow, modified_workflow, image_filename, prompt_text)
        
        # Save both formats for inspection
        self.save_modified_workflow(modified_workflow, "/tmp/modified_workflow_api.json")
        self.save_ui_compatible_workflow(modified_workflow, original_workflow_data, 
                                        image_filename, prompt_text, "/tmp/modified_workflow_ui.json")
        
        # Queue execution
        prompt_id = self.queue_prompt(modified_workflow)
        
        print("=" * 50)
        print("🎉 Workflow submitted successfully!")
        print(f"📁 Output will appear in ComfyUI/output/")
        print("=" * 50)
        
        return prompt_id


def main():
    """Example usage of the ComfyUI controller."""
    if len(sys.argv) < 5:
        print("Usage: python comfyui_api.py <instance_id> <ssh_host> <ssh_port> <image_path> \"<prompt>\"")
        print("Example: python comfyui_api.py 12345 ssh5.vast.ai 22222 ./image.jpg \"A beautiful sunset\"")
        sys.exit(1)
    
    instance_id = sys.argv[1]
    ssh_host = sys.argv[2]
    ssh_port = int(sys.argv[3])
    image_path = sys.argv[4]
    prompt = sys.argv[5] if len(sys.argv) > 5 else "A beautiful scene"
    
    # Create controller
    controller = ComfyUIController(instance_id, ssh_host, ssh_port)
    
    try:
        # Connect
        if not controller.connect():
            sys.exit(1)
        
        # Run workflow
        prompt_id = controller.run_workflow(image_path, prompt)
        
        print(f"\n✅ Success! Your job ID is: {prompt_id}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
    finally:
        controller.disconnect()


if __name__ == "__main__":
    main()