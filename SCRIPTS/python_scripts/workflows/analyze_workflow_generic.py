#!/usr/bin/env python3
"""
Generic Workflow Template Analyzer - Works with ANY ComfyUI workflow
Simply extracts configurable parameters and removes UI clutter.
"""

import sys
import os
import json
import argparse
from pathlib import Path

def clean_workflow_for_config(workflow_data):
    """
    Clean workflow by removing UI clutter and extracting only configurable parts.
    This is completely generic - works with any workflow structure.
    """
    cleaned = {
        "workflow_info": {
            "id": workflow_data.get("id"),
            "name": "",  # Will be filled from filename
            "description": "Auto-generated configuration template"
        },
        "nodes": {}
    }
    
    nodes = workflow_data.get("nodes", [])
    
    for node in nodes:
        node_id = str(node.get("id"))
        node_type = node.get("type")
        node_title = node.get("title", f"{node_type}_{node_id}")
        
        # Extract only the essential configurable parts
        clean_node = {
            "type": node_type,
            "title": node_title,
            "configurable": extract_configurable_values(node)
        }
        
        # Only include nodes that have configurable values
        if clean_node["configurable"]:
            cleaned["nodes"][node_id] = clean_node
    
    # Preserve links but in a cleaner format
    if "links" in workflow_data:
        cleaned["links"] = workflow_data["links"]
    
    return cleaned

def extract_configurable_values(node):
    """
    Generic extraction of configurable values from any node.
    Focuses on widget_values which are the user-configurable parameters.
    """
    configurable = {}
    
    # Extract widget values (these are always user-configurable)
    widgets_values = node.get("widgets_values", [])
    if widgets_values:
        configurable["widgets_values"] = widgets_values
    
    # Extract input widgets (combo boxes, text inputs, etc.)
    inputs = node.get("inputs", [])
    configurable_inputs = {}
    
    for inp in inputs:
        # Look for inputs that have widgets (user-configurable)
        if "widget" in inp:
            widget_name = inp["widget"]["name"]
            # This indicates a user-configurable parameter
            configurable_inputs[widget_name] = {
                "type": inp.get("type"),
                "current_value": None  # Will be filled from widgets_values if available
            }
    
    if configurable_inputs:
        configurable["input_widgets"] = configurable_inputs
    
    return configurable

def format_for_easy_editing(cleaned_workflow):
    """
    Further format the cleaned workflow to make it super easy to edit.
    Group similar node types and provide clear parameter names.
    """
    workflow_name = cleaned_workflow["workflow_info"]["name"]
    default_provisioning_script = f"{workflow_name}.sh"
    
    formatted = {
        "workflow_info": cleaned_workflow["workflow_info"],
        "instance_config": {
            "gpu_name": "RTX 5090",
            "gpu_index": 0,
            "provisioning_script": default_provisioning_script,
            "note": "Instance creation settings - used when creating new instances for this workflow"
        },
        "configurable_parameters": {}
    }
    
    # Group nodes by type for easier editing
    for node_id, node_data in cleaned_workflow["nodes"].items():
        node_type = node_data["type"]
        node_title = node_data["title"]
        
        # Create a section for this node type if it doesn't exist
        if node_type not in formatted["configurable_parameters"]:
            formatted["configurable_parameters"][node_type] = {}
        
        # Add this specific node instance
        instance_key = f"{node_id}_{node_title}".replace(" ", "_")
        formatted["configurable_parameters"][node_type][instance_key] = {
            "node_id": int(node_id),
            "title": node_title,
            "parameters": node_data["configurable"]
        }
    
    # Preserve links for reconstruction
    if "links" in cleaned_workflow:
        formatted["workflow_links"] = cleaned_workflow["links"]
    
    return formatted

def create_user_friendly_template(formatted_workflow):
    """
    Create the most user-friendly version possible.
    This extracts just the values users typically want to change.
    """
    workflow_name = formatted_workflow["workflow_info"]["name"]
    default_provisioning_script = f"{workflow_name}.sh"
    
    template = {
        "workflow_name": workflow_name,
        "description": "Edit the values below, then use with execute_workflow_config.py",
        "instance_config": {
            "gpu_name": "RTX 5090",
            "gpu_index": 0,
            "provisioning_script": default_provisioning_script,
            "note": "Instance creation settings - used when creating new instances for this workflow"
        },
        "parameters": {}
    }
    
    # Extract common parameter patterns
    for node_type, instances in formatted_workflow["configurable_parameters"].items():
        
        for instance_name, instance_data in instances.items():
            params = instance_data["parameters"]
            
            # Create a user-friendly parameter group
            if params:
                template["parameters"][instance_name] = {
                    "node_type": node_type,
                    "node_id": instance_data["node_id"],
                    "title": instance_data["title"],
                    "values": params.get("widgets_values", []),
                    "note": f"Configurable parameters for {node_type}"
                }
    
    # Keep the original structure for reconstruction
    template["_internal"] = {
        "original_structure": formatted_workflow,
        "note": "This section is used internally for workflow reconstruction"
    }
    
    return template

def analyze_workflow(workflow_path, output_format="user_friendly"):
    """
    Analyze any workflow and extract configurable parameters.
    
    output_format options:
    - "user_friendly": Simple template for end users
    - "detailed": More structured but still clean
    - "minimal": Just the essential configurable parts
    """
    print(f"🔍 Analyzing workflow: {workflow_path}")
    
    with open(workflow_path, 'r') as f:
        workflow_data = json.load(f)
    
    # Get workflow name from filename
    workflow_name = Path(workflow_path).stem
    
    # Step 1: Clean the workflow
    cleaned = clean_workflow_for_config(workflow_data)
    cleaned["workflow_info"]["name"] = workflow_name
    
    # Step 2: Format based on requested output
    if output_format == "minimal":
        return cleaned
    elif output_format == "detailed":
        return format_for_easy_editing(cleaned)
    else:  # user_friendly
        formatted = format_for_easy_editing(cleaned)
        return create_user_friendly_template(formatted)

def main():
    parser = argparse.ArgumentParser(description="Generic ComfyUI workflow analyzer - works with ANY workflow")
    parser.add_argument("workflow_file", help="Path to workflow JSON file")
    parser.add_argument("--output", "-o", help="Output path (auto-generated if not specified)")
    parser.add_argument("--format", "-f", choices=["user_friendly", "detailed", "minimal"], 
                       default="user_friendly", help="Output format")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty print to console")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.workflow_file):
        print(f"❌ Workflow file not found: {args.workflow_file}")
        sys.exit(1)
    
    try:
        # Analyze the workflow
        result = analyze_workflow(args.workflow_file, args.format)
        
        # Determine output path
        if args.output:
            output_path = args.output
        else:
            workflow_name = Path(args.workflow_file).stem
            script_dir = Path(__file__).parent.parent.parent.parent
            output_path = script_dir / "TEMPLATES" / "configs" / f"{workflow_name}-{args.format}.json"
        
        # Save result
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"✅ Configuration saved: {output_path}")
        
        # Pretty print if requested
        if args.pretty:
            print(f"\n📋 Generated Configuration ({args.format} format):")
            print("=" * 60)
            print(json.dumps(result, indent=2))
        
        # Show statistics
        if args.format == "user_friendly" and "parameters" in result:
            param_count = len(result["parameters"])
            print(f"\n📊 Found {param_count} configurable node instances")
            
            # Show node types found
            node_types = set()
            for param_info in result["parameters"].values():
                node_types.add(param_info["node_type"])
            
            print(f"🎯 Node types: {', '.join(sorted(node_types))}")
        
        print(f"\n💡 Usage:")
        print(f"1. Edit: {output_path}")
        print(f"2. Run: python execute_workflow_config.py <instance_id> {Path(output_path).name}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()