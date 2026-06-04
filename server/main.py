from mcp.server.fastmcp import FastMCP, Context
import json
import os
import time
import asyncio
import logging
import subprocess
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import Dict, Any, Optional
import sys
import win32gui
import win32ui
import win32con
import win32api
from PIL import Image
import io
import base64
import glob
import re
import netlist as netlist_mod

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for more detailed logs
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Output to console
        logging.FileHandler(str(Path(__file__).with_name('altium_mcp.log')))  # Also log to file
    ]
)
logger = logging.getLogger("AltiumMCPServer")

# Set MCP_DIR to the directory of the current Python file
MCP_DIR = Path(__file__).parent
CONFIG_FILE = MCP_DIR / "config.json"
DEFAULT_SCRIPT_PATH = MCP_DIR / "AltiumScript" / "Altium_API.PrjScr"

# Use a fixed exchange directory for request/response JSON files.
# Both the Python MCP server and the Altium DelphiScript need to independently
# resolve to the same directory. C:\Users\Public is writable by all users and
# exists on every Windows machine. This avoids fragile script-project-path
# resolution that breaks when Altium caches stale script projects.
EXCHANGE_DIR = Path("C:/Users/Public/altium_mcp")
EXCHANGE_DIR.mkdir(exist_ok=True)
REQUEST_FILE = EXCHANGE_DIR / "request.json"
RESPONSE_FILE = EXCHANGE_DIR / "response.json"

# Initialize FastMCP server
mcp = FastMCP("AltiumMCP", description="Altium integration through the Model Context Protocol")

class AltiumConfig:
    def __init__(self):
        self.altium_exe_path = ""
        self.script_path = str(DEFAULT_SCRIPT_PATH)
        self.load_config()
    
    def load_config(self):
        """Load configuration from file or create default if it doesn't exist"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self.altium_exe_path = config.get("altium_exe_path", "")
                    self.script_path = config.get("script_path", str(DEFAULT_SCRIPT_PATH))
                logger.info(f"Loaded configuration from {CONFIG_FILE}")
            except Exception as e:
                logger.error(f"Error loading configuration: {e}")
                self._create_default_config()
        else:
            logger.info("No configuration file found, creating default")
            self._create_default_config()
    
    def _create_default_config(self):
        """Create a default configuration file with improved Altium executable discovery"""
        
        # Try to find Altium directories dynamically
        altium_base_path = r"C:\Program Files\Altium"
        altium_exe_path = None
        
        if os.path.exists(altium_base_path):
            # Find all directories that match the pattern AD*
            ad_dirs = glob.glob(os.path.join(altium_base_path, "AD*"))
            
            if ad_dirs:
                # Sort directories by version number (extract the number after "AD")
                def get_version_number(dir_path):
                    match = re.search(r"AD(\d+)", os.path.basename(dir_path))
                    if match:
                        return int(match.group(1))
                    return 0
                
                # Sort directories by version number (highest first)
                ad_dirs.sort(key=get_version_number, reverse=True)
                
                # Try each directory until we find one with X2.EXE
                for ad_dir in ad_dirs:
                    potential_exe = os.path.join(ad_dir, "X2.EXE")
                    if os.path.exists(potential_exe):
                        altium_exe_path = potential_exe
                        break
        
        # Set the found path (or empty string if nothing found)
        self.altium_exe_path = altium_exe_path if altium_exe_path else ""
        
        # Save the configuration
        self.save_config()
    
    def save_config(self):
        """Save configuration to file"""
        config = {
            "altium_exe_path": self.altium_exe_path,
            "script_path": self.script_path
        }
        
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
            logger.info(f"Saved configuration to {CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
    
    def verify_paths(self):
        """Verify that the paths in the configuration exist, prompt for input if they don't"""

        # Initialize variables
        root = None
        paths_verified = True
        
        # Check Altium executable
        if not self.altium_exe_path or not os.path.exists(self.altium_exe_path):
            paths_verified = False
            
            # Before prompting, try an automatic discovery
            altium_base_path = r"C:\Program Files\Altium"
            if os.path.exists(altium_base_path):
                logger.info(f"Attempting automatic discovery in {altium_base_path}")
                # Find all directories that match the pattern AD*
                ad_dirs = glob.glob(os.path.join(altium_base_path, "AD*"))
                
                if ad_dirs:
                    # Sort directories by version number (extract the number after "AD")
                    def get_version_number(dir_path):
                        match = re.search(r"AD(\d+)", os.path.basename(dir_path))
                        if match:
                            return int(match.group(1))
                        return 0
                    
                    # Sort directories by version number (highest first)
                    ad_dirs.sort(key=get_version_number, reverse=True)
                    
                    # Try each directory until we find one with X2.EXE
                    for ad_dir in ad_dirs:
                        potential_exe = os.path.join(ad_dir, "X2.EXE")
                        if os.path.exists(potential_exe):
                            self.altium_exe_path = potential_exe
                            logger.info(f"Automatically found Altium at: {self.altium_exe_path}")
                            print(f"Automatically found Altium at: {self.altium_exe_path}")
                            paths_verified = True
                            break
            
            # If automatic discovery failed, prompt for input
            if not self.altium_exe_path or not os.path.exists(self.altium_exe_path):
                if root is None:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.withdraw()  # Hide the main window
                
                logger.info("Altium executable not found. Prompting user for selection...")
                print(f"Altium executable not found. Searched in:")
                print(f"  - Automatically scanned C:\\Program Files\\Altium\\AD*\\X2.EXE")
                print(f"  - Last known path: {self.altium_exe_path}")
                print("Please select the Altium X2.EXE file...")
                
                self.altium_exe_path = filedialog.askopenfilename(
                    title="Select Altium Executable",
                    filetypes=[("Executable files", "*.exe")],  # Only allow .exe files
                    initialdir="C:/Program Files/Altium"
                )
                
                if not self.altium_exe_path:
                    logger.error("No Altium executable selected. Some functionality may not work.")
                    print("Warning: No Altium executable selected. Automatic script execution will be disabled.")
                    paths_verified = False
        
        # Check script path
        if not os.path.exists(self.script_path):
            paths_verified = False
            
            if root is None:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()  # Hide the main window
            
            logger.info(f"Script file not found at {self.script_path}. Prompting user for selection...")
            print(f"Script file not found at {self.script_path}. Please select the Altium project file...")
            
            selected_path = filedialog.askopenfilename(
                title="Select Altium Project File",
                filetypes=[("Altium Project files", "*.PrjScr")],  # Changed to PrjScr for script project
                initialdir=str(MCP_DIR)
            )
            
            if selected_path:
                self.script_path = selected_path
            else:
                logger.error("No script file selected. Some functionality may not work.")
                print("Warning: No script file selected. Please make sure to create one.")
                paths_verified = False
        
        # Clean up tkinter root if created
        if root is not None:
            root.destroy()
        
        # Save the updated configuration
        self.save_config()
        
        return paths_verified

class AltiumBridge:
    def __init__(self):
        # Ensure the MCP directory exists
        MCP_DIR.mkdir(exist_ok=True)
        
        # Load configuration
        self.config = AltiumConfig()
        self.config.verify_paths()
    
    async def execute_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a command in Altium via the bridge script"""
        try:
            # Clean up any existing response file
            if RESPONSE_FILE.exists():
                RESPONSE_FILE.unlink()
            
            # Write the request file with command and parameters
            with open(REQUEST_FILE, "w") as f:
                json.dump({
                    "command": command,
                    **params  # Include parameters directly in the main JSON object
                }, f, indent=2)
            
            logger.info(f"Wrote request file for command: {command}")
            
            # Run the Altium script
            success = await self.run_altium_script()
            if not success:
                return {"success": False, "error": "Failed to run Altium script"}
            
            # Wait for the response file
            logger.info(f"Waiting for response file to appear...")
            timeout = 120  # seconds
            start_time = time.time()
            while not RESPONSE_FILE.exists() and time.time() - start_time < timeout:
                await asyncio.sleep(0.5)
            
            if not RESPONSE_FILE.exists():
                logger.error("Timeout waiting for response from Altium")
                return {"success": False, "error": "No response received from Altium (timeout)"}
            
            # Read the response file and print it for debugging
            logger.info("Response file found, reading response")
            response_text = ""
            with open(RESPONSE_FILE, "r") as f:
                response_text = f.read()
            
            # Log the raw response for debugging
            logger.info(f"Raw response (first 200 chars): {response_text[:200]}")
            
            # Parse the JSON response with detailed error handling
            try:
                response = json.loads(response_text)
                logger.info(f"Successfully parsed JSON response")
                return response
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON response: {e}")
                logger.error(f"Error at position {e.pos}, line {e.lineno}, column {e.colno}")
                logger.error(f"Character at error position: '{response_text[e.pos:e.pos+10]}...'")
                
                # Try to manually fix common JSON issues
                logger.info("Attempting to fix JSON response...")
                fixed_text = response_text
                
                # Fix 1: If there's a quoted JSON array, try to fix it
                if '"[' in fixed_text and ']"' in fixed_text:
                    fixed_text = fixed_text.replace('"[', '[').replace(']"', ']')
                    logger.info("Fixed double-quoted JSON array")
                
                # Fix 2: Handle escaped quotes in JSON strings
                fixed_text = fixed_text.replace('\\"', '"')
                
                # Try to parse the fixed JSON
                try:
                    fixed_response = json.loads(fixed_text)
                    logger.info("Successfully parsed fixed JSON response")
                    return fixed_response
                except json.JSONDecodeError as e2:
                    logger.error(f"Still failed to parse JSON after fixes: {e2}")
                
                # If all else fails, return a structured error
                return {
                    "success": False, 
                    "error": f"Invalid JSON response: {e}",
                    "raw_response": response_text[:500]  # Include part of the raw response for diagnosis
                }
        
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _resolve_msix_path(virtual_path: str) -> str:
        """Resolve an MSIX-virtualized path to the real filesystem path.

        When Claude Desktop is installed via MSIX (the standard .exe installer
        on modern Windows), file paths are virtualized under AppData\\Roaming\\
        but the real files live at AppData\\Local\\Packages\\Claude_*\\
        LocalCache\\Roaming\\. Child processes of the MSIX app (like Python)
        can see the virtualized paths, but external apps (like Altium) cannot.
        This resolves the path so external processes can find the files.
        """
        appdata = os.environ.get('APPDATA', '')
        if not appdata or not virtual_path.startswith(appdata):
            return virtual_path

        localappdata = os.environ.get('LOCALAPPDATA', '')
        packages_dir = os.path.join(localappdata, 'Packages')
        if not os.path.isdir(packages_dir):
            return virtual_path

        try:
            for item in os.listdir(packages_dir):
                if item.startswith('Claude_'):
                    relative = os.path.relpath(virtual_path, appdata)
                    real_path = os.path.join(packages_dir, item, 'LocalCache', 'Roaming', relative)
                    if os.path.exists(real_path):
                        logger.info(f"Resolved MSIX path: {virtual_path} -> {real_path}")
                        return real_path
        except Exception as e:
            logger.warning(f"Error resolving MSIX path: {e}")

        return virtual_path

    async def run_altium_script(self) -> bool:
        """Run the Altium bridge script"""
        if not os.path.exists(self.config.altium_exe_path):
            logger.error(f"Altium executable not found at: {self.config.altium_exe_path}")
            print(f"Error: Altium executable not found. Please check the configuration.")
            return False

        if not os.path.exists(self.config.script_path):
            logger.error(f"Script file not found at: {self.config.script_path}")
            print(f"Error: Script file not found. Please check the configuration.")
            return False

        try:
            # Resolve MSIX-virtualized path so Altium (an external process
            # outside the MSIX sandbox) can find the script files
            script_path = self._resolve_msix_path(self.config.script_path)

            # Command format: "X2.EXE" -RScriptingSystem:RunScript(ProjectName="path\file.PrjScr"|ProcName="ModuleName>Run")
            command = f'"{self.config.altium_exe_path}" -RScriptingSystem:RunScript(ProjectName="{script_path}"^|ProcName="Altium_API>Run")'
            
            logger.info(f"Running command: {command}")
            
            # Start the process
            process = subprocess.Popen(command, shell=True)
            
            # Don't wait for completion - Altium will run the script and generate the response
            logger.info(f"Launched Altium with script, process ID: {process.pid}")
            return True
        
        except Exception as e:
            logger.error(f"Error launching Altium: {e}")
            return False

# Create a global bridge instance
altium_bridge = AltiumBridge()

@mcp.tool()
async def get_all_component_property_names(ctx: Context) -> str:
    """
    Get all available component property names (JSON keys) from all components
    
    Returns:
        str: JSON array with all unique property names
    """
    logger.info("Getting all component property names")
    
    # Execute the command in Altium to get component data
    response = await altium_bridge.execute_command(
        "get_all_component_data", 
        {}
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting component data: {error_msg}")
        return json.dumps({"error": f"Failed to get component data: {error_msg}"})
    
    # Get the component data
    components_data = response.get("result", [])
    
    if not components_data:
        logger.info("No component data found")
        return json.dumps({"error": "No component data found"})
    
    try:
        # Parse the data if it's a string
        if isinstance(components_data, str):
            components_list = json.loads(components_data)
        else:
            components_list = components_data
            
        # Extract all unique property names from all components
        property_names = set()
        for component in components_list:
            property_names.update(component.keys())
        
        # Convert set to sorted list for consistent output
        property_list = sorted(list(property_names))
        
        logger.info(f"Found {len(property_list)} unique property names")
        return json.dumps(property_list, indent=2)
    except Exception as e:
        logger.error(f"Error processing component data: {e}")
        return json.dumps({"error": f"Failed to process component data: {str(e)}"})

@mcp.tool()
async def get_component_property_values(ctx: Context, property_name: str) -> str:
    """
    Get values of a specific property for all components
    
    Args:
        property_name (str): The name of the property to get values for
    
    Returns:
        str: JSON array with objects containing designator and property value
    """
    logger.info(f"Getting values for property: {property_name}")
    
    # Execute the command in Altium to get component data
    response = await altium_bridge.execute_command(
        "get_all_component_data", 
        {}
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting component data: {error_msg}")
        return json.dumps({"error": f"Failed to get component data: {error_msg}"})
    
    # Get the component data
    components_data = response.get("result", [])
    
    if not components_data:
        logger.info("No component data found")
        return json.dumps({"error": "No component data found"})
    
    try:
        # Parse the data if it's a string
        if isinstance(components_data, str):
            components_list = json.loads(components_data)
        else:
            components_list = components_data
            
        # Extract the property values along with designators
        property_values = []
        for component in components_list:
            designator = component.get("designator")
            if designator and property_name in component:
                property_values.append({
                    "designator": designator,
                    "value": component.get(property_name)
                })
        
        logger.info(f"Found {len(property_values)} components with property '{property_name}'")
        return json.dumps(property_values, indent=2)
    except Exception as e:
        logger.error(f"Error processing component data: {e}")
        return json.dumps({"error": f"Failed to process component data: {str(e)}"})
    
@mcp.tool()
async def get_symbol_placement_rules(ctx: Context) -> str:
    """
    Get schematic symbol placement rules from a local configuration file
    
    Returns:
        str: JSON object with rules for placing pins on schematic symbols
    """
    logger.info("Getting symbol placement rules")
    
    # Define the rules file path in the MCP directory
    rules_file_path = MCP_DIR / "symbol_placement_rules.txt"
    
    # Check if the rules file exists
    if not rules_file_path.exists():
        logger.info("Symbol placement rules file not found, suggesting creation")
        
        # Default rules content
        default_rules = (
            "Only place pins on the left and right side of the symbol. "
            "Place power rail pins at the upper right, ground pins in the bottom left, "
            "no connect pins in the bottom right, inputs on the left, outputs on the right, "
            "and try to group other pins together by similar functionality (for example, SPI, I2C, RGMII, etc.). "
            "Always separate groups by 100mil gaps unless there is extra spacing, then space out groups equal distance from each other. "
        )
        
        # Create a helpful message for the user
        message = {
            "success": False,
            "error": f"Rules file not found at: {rules_file_path}",
            "message": f"Let the user know that they can optionally update the file {rules_file_path} with custom symbol placement rules. "
                      f"Suggested content: {default_rules}"
        }
        
        return json.dumps(message, indent=2)
    
    # Read the rules file if it exists
    try:
        with open(rules_file_path, "r") as f:
            rules_content = f.read()
        
        logger.info("Successfully read symbol placement rules file")
        
        # Return the rules with a message about how to modify them
        result = {
            "success": True,
            "message": f"Modify {rules_file_path} with custom symbol placement instructions",
            "rules": rules_content
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error reading symbol placement rules file: {e}")
        return json.dumps({
            "success": False,
            "error": f"Failed to read rules file: {str(e)}"
        }, indent=2)

@mcp.tool()
async def get_library_symbol_reference(ctx: Context) -> str:
    """
    Get the currently open symbol from a schematic library to use as reference for creating a new symbol.
    This tool should be used before creating a new symbol to understand the structure of existing symbols.
    
    Returns:
        str: JSON object with the reference symbol data including pins, their types, positions, and orientations
    """
    logger.info("Getting library symbol reference data")
    
    # Execute the command in Altium to get symbol reference data
    response = await altium_bridge.execute_command(
        "get_library_symbol_reference", 
        {}
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting symbol reference: {error_msg}")
        return json.dumps({"error": f"Failed to get symbol reference: {error_msg}"})
    
    # Get the symbol reference data
    symbol_data = response.get("result", {})
    
    if not symbol_data:
        logger.info("No symbol reference data found")
        return json.dumps({"error": "No symbol reference data found or no symbol is currently selected in the library"})
    
    logger.info(f"Retrieved symbol reference data")
    return json.dumps(symbol_data, indent=2)

@mcp.tool()
async def search_library_symbol(ctx: Context, symbol_name: str, library_path: str = "") -> str:
    """
    Search for a symbol by name in a schematic library (.SchLib) and navigate to it.
    Supports partial name matching (case-insensitive). Returns all matches and navigates
    to the best match (exact match preferred, otherwise first partial match).

    This tool will automatically open the library file in Altium if a path is provided,
    so no SchLib needs to be open beforehand.

    Args:
        symbol_name (str): Name or partial name of the symbol to search for
        library_path (str): Full file path to the .SchLib file (e.g. "N:\\Libs\\Integrated_Circuits.SchLib").
                           The tool will open this file in Altium if it is not already open.
                           If empty, uses the currently open library.
                           If no library is open and no path is provided, ask the user for the file path.

    Returns:
        str: JSON object with search results including matches, navigated symbol, and full symbol list
    """
    logger.info(f"Searching for symbol: {symbol_name} in library: {library_path or '(current)'}")

    # Execute the command in Altium
    params = {"symbol_name": symbol_name}
    if library_path:
        params["library_path"] = library_path

    response = await altium_bridge.execute_command(
        "search_library_symbol",
        params
    )

    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error searching for symbol: {error_msg}")
        return json.dumps({"error": f"Failed to search for symbol: {error_msg}"})

    # Get the result data
    result = response.get("result", {})

    if not result:
        logger.info("No search results returned")
        return json.dumps({"error": "No results returned from symbol search"})

    logger.info(f"Symbol search complete. Found: {result.get('found', False)}")
    return json.dumps(result, indent=2)

@mcp.tool()
async def create_schematic_symbol(ctx: Context, symbol_name: str, description: str, pins: list, part_count: int = 1) -> str:
    """
    Before executing, run get_symbol_placement_rules first.
    Create a new schematic symbol in the current library with the specified pins
    Instructions: pins should be grouped together via function and only placed on
                  the left and right side in 100 mil increments

    Pin name inversion/overbar: To show an overbar on a pin name (for active-low signals),
                  place a backslash after EACH character that should be overbarred.
                  Examples: R\E\S\E\T\ renders as RESET with overbar.
                           C\S\/A0 renders as CS with overbar followed by /A0 without overbar.
                  Do NOT use ~{...} or other notation — only the backslash-per-character format works in Altium.

    Args:
        symbol_name (str): Name of the symbol to create
        description (str): Description of the schematic symbol
        pins (list): List of pin data in format ["pin_number|pin_name|pin_type|pin_orientation|x|y|owner_part_id", ...]
                    Pin types: eElectricHiZ, eElectricInput, eElectricIO, eElectricOpenCollector,
                               eElectricOpenEmitter, eElectricOutput, eElectricPassive, eElectricPower
                    Pin orientations: eRotate0 (right), eRotate90 (down), eRotate180 (left), eRotate270 (up)
                    X,Y coordinates in mils
                    owner_part_id (optional): Part number the pin belongs to (1-based).
                               Use 0 for pins shared across all parts (e.g. power/GND).
                               Defaults to 1 if omitted. Only needed for multi-part symbols.
        part_count (int): Number of parts in the symbol (default 1).
                         Use >1 for multi-part symbols like quad op-amps or hex buffers.

    Returns:
        str: JSON object with the result of the component creation
    """
    logger.info(f"Creating schematic symbol: {symbol_name} with {len(pins)} pins, {part_count} part(s)")

    # Execute the command in Altium to create a symbol with pins
    response = await altium_bridge.execute_command(
        "create_schematic_symbol",
        {
            "symbol_name": symbol_name,
            "description": description,
            "part_count": part_count,
            "pins": pins
        }
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error creating symbol: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to create symbol: {error_msg}"})
    
    # Get the result data
    result = response.get("result", {})
    
    logger.info(f"Symbol {symbol_name} created successfully with {len(pins)} pins")
    return json.dumps(result, indent=2)

@mcp.tool()
async def place_net_labels(ctx: Context, assignments: list) -> str:
    """
    Place net labels on schematic component pins to define connectivity.
    Altium treats all pins sharing the same net label name as electrically connected.
    No wires are needed — net label names are the connection.

    Duplicate labels on the same pin may cause ERC warnings.

    Args:
        assignments (list): Pipe-delimited strings: "DESIGNATOR|PIN_NAME|NET_NAME"
            e.g. ["U1|VCC|3V3", "U2|VCC|3V3", "C1|1|3V3"]
            PIN_NAME can be the pin name (e.g. "VCC") or pin number (e.g. "1").

    Returns:
        str: JSON with placed_count, skipped_count, and not_found list
    """
    logger.info(f"place_net_labels: {len(assignments)} assignments")
    response = await altium_bridge.execute_command(
        "place_net_labels",
        {"assignments": assignments}
    )
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error placing net labels: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to place net labels: {error_msg}"})
    return json.dumps(response.get("result", {}), indent=2)

@mcp.tool()
async def connect_pins(ctx: Context, assignments: list) -> str:
    """
    Draw wires between two pins on the same schematic sheet so they share a net.
    If one pin is already on a net (e.g. via an existing port or label), the other
    joins that net electrically.

    Args:
        assignments (list): Pipe-delimited strings:
            - Same component: "DESIGNATOR|PIN_A|PIN_B" e.g. ["IC9|25|26"]
            - Two components: "DES_A|PIN_A|DES_B|PIN_B"

    Returns:
        str: JSON with connected_count, skipped_count, and not_found list
    """
    logger.info(f"connect_pins: {len(assignments)} assignments")
    response = await altium_bridge.execute_command(
        "connect_pins",
        {"assignments": assignments}
    )
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error connecting pins: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to connect pins: {error_msg}"})
    return json.dumps(response.get("result", {}), indent=2)

@mcp.tool()
async def place_power_ports(ctx: Context, assignments: list) -> str:
    """
    Place Altium power port symbols (VCC, GND, etc.) on schematic component pins.
    GND/VSS/AGND/PGND use the ground symbol pointing down; other nets use a bar pointing up.

    Args:
        assignments (list): Pipe-delimited strings: "DESIGNATOR|PIN_NAME|NET_NAME"
            e.g. ["U1|GND|GND", "C1|2|GND", "U2|VCC|3V3"]

    Returns:
        str: JSON with placed_count, skipped_count, and not_found list
    """
    logger.info(f"place_power_ports: {len(assignments)} assignments")
    response = await altium_bridge.execute_command(
        "place_power_ports",
        {"assignments": assignments}
    )
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error placing power ports: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to place power ports: {error_msg}"})
    return json.dumps(response.get("result", {}), indent=2)

@mcp.tool()
async def get_unconnected_pins(ctx: Context) -> str:
    """
    Return all pins on schematic sheets in the open project that have no net assigned.

    Requires an open Altium project (.PrjPcb), not just a standalone .SchDoc, because it
    calls DM_Compile to resolve connectivity. Compilation may take several seconds.

    Returns:
        str: JSON array of {designator, pin_name, pin_number} objects
    """
    logger.info("get_unconnected_pins")
    response = await altium_bridge.execute_command("get_unconnected_pins", {})
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting unconnected pins: {error_msg}")
        return json.dumps({"error": f"Failed to get unconnected pins: {error_msg}"})
    pins_data = response.get("result", [])
    if isinstance(pins_data, str):
        try:
            pins_data = json.loads(pins_data)
        except json.JSONDecodeError:
            pass
    return json.dumps(pins_data, indent=2)

@mcp.tool()
async def place_diff_pair_labels(
    ctx: Context,
    pos_assignment: str,
    neg_assignment: str,
    add_directive: bool = True,
) -> str:
    """
    Place net labels for a differential pair on two schematic component pins.
    Follows Altium's _P/_N naming convention.

    Args:
        pos_assignment (str): Pipe-delimited positive pin: "DESIGNATOR|PIN_NAME|NET_NAME_P"
        neg_assignment (str): Pipe-delimited negative pin: "DESIGNATOR|PIN_NAME|NET_NAME_N"
        add_directive (bool): If True, also place a Differential Pair directive
            (a Parameter Set with a DIFFPAIR parameter) touching the positive net.

    Returns:
        str: JSON with placed_count, skipped_count, not_found, and (if requested)
             directives_placed.
    """
    response = await altium_bridge.execute_command(
        "place_net_labels",
        {"assignments": [pos_assignment, neg_assignment]},
    )
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error placing diff pair labels: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to place diff pair labels: {error_msg}"})
    result = _coerce(response.get("result", {}))
    if add_directive:
        rd = await altium_bridge.execute_command(
            "place_diff_pair_directives", {"assignments": [pos_assignment]})
        resd = _coerce(rd.get("result", {}))
        if isinstance(result, dict) and isinstance(resd, dict):
            result["directives_placed"] = resd.get("directives_placed", 0)
    return json.dumps(result, indent=2)

@mcp.tool()
async def place_bus_labels(
    ctx: Context,
    bus_name: str,
    bit_range: list,
    assignments: list,
) -> str:
    """
    Place indexed net labels for a multi-bit bus across multiple component pins in one call.

    Args:
        bus_name (str): Base bus name for {bus} placeholder (e.g. "DATA")
        bit_range (list): Two-element list [low, high] inclusive (e.g. [0, 7])
        assignments (list): Pipe-delimited templates with {i} and/or {bus}:
            e.g. ["U1|D{i}|DATA{i}", "U4|D{i}|DATA{i}"]

    Returns:
        str: JSON with placed_count, skipped_count, not_found list
    """
    if len(bit_range) != 2:
        return json.dumps({"success": False, "error": "bit_range must be a two-element list [low, high]"})
    expanded = []
    for template in assignments:
        for bit in range(bit_range[0], bit_range[1] + 1):
            expanded.append(template.replace("{i}", str(bit)).replace("{bus}", bus_name))
    logger.info(f"place_bus_labels: expanded to {len(expanded)} assignments")
    response = await altium_bridge.execute_command("place_net_labels", {"assignments": expanded})
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error placing bus labels: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to place bus labels: {error_msg}"})
    return json.dumps(response.get("result", {}), indent=2)


# =========================================================================== #
# JITX-like declarative netlist layer
#
# These tools turn a declarative netlist (a set of named nets, each listing the
# pins it connects) into the existing schematic primitives, picking a placement
# strategy automatically (power ports / wires / net labels / bus / diff). The
# parsing/planning/diff logic lives in netlist.py (pure Python, unit-tested);
# everything Altium-touching stays here.
# =========================================================================== #
def _coerce(value):
    """Bridge results may arrive as JSON strings; parse them when possible."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def _resolve_netlist_path(file_path: str) -> Path:
    """Resolve a (possibly relative) netlist path against sensible roots."""
    p = Path(file_path)
    candidates = [p, MCP_DIR / file_path, MCP_DIR.parent / file_path, Path.cwd() / file_path]
    for c in candidates:
        if c.exists():
            return c
    return p


async def _read_pin_nets():
    """Read actual pin->net connectivity from Altium. Returns (data, error)."""
    resp = await altium_bridge.execute_command("get_pin_nets", {})
    if not resp.get("success", False):
        return None, resp.get("error", "Unknown error")
    data = _coerce(resp.get("result", []))
    if isinstance(data, str):
        return None, data  # e.g. "ERROR: No project is currently open."
    if isinstance(data, dict) and "error" in data:
        return None, data["error"]
    if not isinstance(data, list):
        return None, f"Unexpected get_pin_nets result type: {type(data).__name__}"
    return data, None


def _expand_bus_assignments(payload: dict) -> list:
    out = []
    lo, hi = payload["bit_range"]
    step = 1 if hi >= lo else -1
    for tmpl in payload["assignments"]:
        for i in range(lo, hi + step, step):
            out.append(tmpl.replace("{i}", str(i)).replace("{bus}", payload["bus_name"]))
    return out


async def _dispatch_action(action) -> dict:
    """Execute one planner Action against Altium via the existing primitives."""
    m, p = action.method, action.payload
    base = {"net": action.net, "method": m}

    if m == "net_labels":
        r = await altium_bridge.execute_command("place_net_labels", {"assignments": p["assignments"]})
    elif m == "power_ports":
        r = await altium_bridge.execute_command("place_power_ports", {"assignments": p["assignments"]})
    elif m == "bus_labels":
        r = await altium_bridge.execute_command(
            "place_net_labels", {"assignments": _expand_bus_assignments(p)})
    elif m == "net_class":
        r = await altium_bridge.execute_command(
            "create_net_class", {"class_name": p["class_name"], "net_names": p["net_names"]})
    elif m == "diff_pairs":
        agg = {"placed_count": 0, "skipped_existing": 0, "conflict_count": 0,
               "skipped_count": 0, "directives_placed": 0}
        ok = True
        for pair in p["pairs"]:
            r = await altium_bridge.execute_command(
                "place_net_labels",
                {"assignments": [pair["pos_assignment"], pair["neg_assignment"]]})
            ok = ok and r.get("success", False)
            res = _coerce(r.get("result", {}))
            if isinstance(res, dict):
                for k in agg:
                    agg[k] += res.get(k, 0)
        # Place the differential-pair directive on each positive net (best-effort:
        # labels already define the pair via _P/_N, so a directive failure is
        # non-fatal and only reduces directives_placed).
        pos_assignments = [pair["pos_assignment"] for pair in p["pairs"]]
        rd = await altium_bridge.execute_command(
            "place_diff_pair_directives", {"assignments": pos_assignments})
        resd = _coerce(rd.get("result", {}))
        if isinstance(resd, dict):
            agg["directives_placed"] += resd.get("directives_placed", 0)
        base.update(success=ok, result=agg)
        return base
    elif m == "wire":
        r = await altium_bridge.execute_command("connect_pins", {"assignments": p["assignments"]})
        res = _coerce(r.get("result", {}))
        connected = 0
        if isinstance(res, dict):
            connected = res.get("connected_count", 0) + res.get("skipped_existing", 0)
        if r.get("success", False) and connected < 1:
            # Wire could not be drawn (e.g. pins not actually on the same sheet)
            # -> fall back to net labels so the net is still realized.
            r = await altium_bridge.execute_command(
                "place_net_labels", {"assignments": p["fallback_assignments"]})
            base["method"] = "net_labels (wire fallback)"
    else:
        return {**base, "success": False, "error": f"unknown method '{m}'"}

    base.update(success=r.get("success", False), result=_coerce(r.get("result", {})))
    if r.get("error"):
        base["error"] = r["error"]
    return base


def _summarize(results: list) -> dict:
    keys = ("placed_count", "skipped_existing", "conflict_count",
            "connected_count", "skipped_count")
    summary = {k: 0 for k in keys}
    for r in results:
        res = r.get("result", {})
        if isinstance(res, dict):
            for k in keys:
                summary[k] += res.get(k, 0)
    summary["actions"] = len(results)
    return summary


async def _apply_netlist_obj(nl) -> dict:
    """Validate against the live schematic, then plan + place. Aborts on errors."""
    data, err = await _read_pin_nets()
    if err:
        return {"success": False, "error": f"could not read schematic connectivity: {err}"}
    index = netlist_mod.build_pin_index(data)

    errors = netlist_mod.validate(nl, index)
    if errors:
        return {"success": False, "validation_errors": errors,
                "hint": "Nothing was placed. Fix the pin references and re-run."}

    actions = netlist_mod.plan(nl, index)
    results = [await _dispatch_action(a) for a in actions]
    return {"success": all(r.get("success", False) for r in results),
            "summary": _summarize(results), "actions": results}


@mcp.tool()
async def get_netlist(ctx: Context) -> str:
    """
    Read the ACTUAL connectivity of every schematic pin in the open project.

    Requires an open Altium project (.PrjPcb); it compiles the project to resolve
    nets (may take a few seconds). This is the read-back used by check_netlist.

    Returns:
        str: JSON array of {designator, pin_name, pin_number, sheet, net} objects,
             where net == "" means the pin is unconnected.
    """
    logger.info("get_netlist")
    data, err = await _read_pin_nets()
    if err:
        return json.dumps({"success": False, "error": err})
    return json.dumps(data, indent=2)


@mcp.tool()
async def connect_nets(ctx: Context, nets: list) -> str:
    """
    Connect one or more nets declaratively in a single call (JITX-style).

    Each net names the pins it joins; the tool validates them against the live
    schematic and AUTO-PICKS how to realize each net: power/ground nets -> power
    ports, simple 2-pin same-sheet nets -> wires, everything else -> net labels.
    Safe to re-run: existing labels/wires are detected and not duplicated.

    Args:
        nets (list): List of net specs, each a dict:
            {"name": "3V3", "pins": ["U1.VCC", "U2.VDD", "C1.1"], "style": "auto"}
            - pins are "DESIGNATOR.PIN" (pin name or number).
            - style (optional): auto | label | wire | power. Default "auto".

    Returns:
        str: JSON report with per-net actions, a summary, and validation_errors
             (if any pin reference is invalid, nothing is placed).
    """
    logger.info(f"connect_nets: {len(nets)} nets")
    nl = netlist_mod.Netlist()
    try:
        for spec in nets:
            name = spec["name"]
            pins = []
            for ref in spec.get("pins", []):
                if "." not in ref:
                    return json.dumps({"success": False,
                                       "error": f"pin '{ref}' must be DESIGNATOR.PIN"})
                des, pin = ref.split(".", 1)
                pins.append(netlist_mod.PinRef(des.strip(), pin.strip()))
            nl.nets.append(netlist_mod.Net(name, pins, spec.get("style", "auto")))
    except (KeyError, TypeError) as e:
        return json.dumps({"success": False, "error": f"malformed net spec: {e}"})

    return json.dumps(await _apply_netlist_obj(nl), indent=2)


@mcp.tool()
async def apply_netlist(ctx: Context, file_path: str) -> str:
    """
    Apply a declarative .netlist file to the open schematic ("make it so").

    Parses the file, validates every pin reference against the live schematic,
    then places net labels / power ports / wires / bus & diff-pair labels using
    auto-mix. Idempotent: re-running places nothing new and reports skipped_existing.
    If any pin reference is invalid, NOTHING is placed and the errors are returned.

    Netlist grammar (see server/netlist_rules.txt):
        power GND 3V3
        net  3V3 (U1.VCC, U2.VDD, C1.1)
        net  UART (U1.PA9 -> U2.RX)
        bus  DATA[0:7] (U1.D{i}, U3.D{i})
        diff USB0 (U1.DP/DM, J1.DP/DN)
        class HighSpeed { USB0_P USB0_N }
        net  I2C (U1.SCL, U2.SCL) style=label

    Args:
        file_path (str): Path to the .netlist file (absolute, or relative to the
            server directory / current directory).

    Returns:
        str: JSON report (actions, summary, validation_errors).
    """
    logger.info(f"apply_netlist: {file_path}")
    path = _resolve_netlist_path(file_path)
    if not path.exists():
        return json.dumps({"success": False, "error": f"file not found: {file_path}"})
    try:
        nl = netlist_mod.parse_netlist(path.read_text(encoding="utf-8"))
    except netlist_mod.NetlistError as e:
        return json.dumps({"success": False, "error": f"parse error: {e}"})
    return json.dumps(await _apply_netlist_obj(nl), indent=2)


@mcp.tool()
async def check_netlist(ctx: Context, file_path: str) -> str:
    """
    Review a .netlist file against the ACTUAL schematic without changing anything.

    Parses the file, reads back real connectivity (get_netlist), and reports, per
    net: OK (all pins on one net), MISSING (a pin not connected), or CONFLICT
    (pins split across nets, or two intent-nets merged). Membership-based, so
    wired nets with Altium-assigned names still verify. This is the "review = a
    command prompt" half of the workflow.

    Args:
        file_path (str): Path to the .netlist file.

    Returns:
        str: JSON {ok, summary, nets:[...], report_text, validation_errors}.
    """
    logger.info(f"check_netlist: {file_path}")
    path = _resolve_netlist_path(file_path)
    if not path.exists():
        return json.dumps({"success": False, "error": f"file not found: {file_path}"})
    try:
        nl = netlist_mod.parse_netlist(path.read_text(encoding="utf-8"))
    except netlist_mod.NetlistError as e:
        return json.dumps({"success": False, "error": f"parse error: {e}"})

    data, err = await _read_pin_nets()
    if err:
        return json.dumps({"success": False, "error": f"could not read connectivity: {err}"})

    index = netlist_mod.build_pin_index(data)
    validation_errors = netlist_mod.validate(nl, index)
    report = netlist_mod.diff(nl, data)
    out = report.to_dict()
    out["success"] = True
    out["report_text"] = report.to_text()
    if validation_errors:
        out["validation_errors"] = validation_errors
    return json.dumps(out, indent=2)


@mcp.tool()
async def export_netlist(ctx: Context, file_path: str = "") -> str:
    """
    Export the open schematic's current connectivity AS a .netlist file.

    Reverse of apply_netlist: bootstraps a declarative netlist from an existing
    design so you can review/edit it as text. Power-style nets are emitted with a
    `power` declaration. Re-applying the exported file should be a no-op.

    Args:
        file_path (str): Where to write the .netlist (optional). If empty, the
            text is only returned, not written.

    Returns:
        str: JSON {success, path, netlist_text}.
    """
    logger.info(f"export_netlist: {file_path or '(return only)'}")
    data, err = await _read_pin_nets()
    if err:
        return json.dumps({"success": False, "error": err})
    text = netlist_mod.netlist_from_pin_nets(data)
    written = ""
    if file_path:
        target = Path(file_path)
        if not target.is_absolute():
            target = MCP_DIR / file_path
        try:
            target.write_text(text, encoding="utf-8")
            written = str(target)
        except OSError as e:
            return json.dumps({"success": False, "error": f"could not write file: {e}",
                               "netlist_text": text})
    return json.dumps({"success": True, "path": written, "netlist_text": text}, indent=2)


@mcp.tool()
async def get_schematic_data(ctx: Context, cmp_designators: list) -> str:
    """
    Get schematic data for components in Altium
    
    Args:
        cmp_designators (list): List of designators of the components (e.g., ["R1", "C5", "U3"])
    
    Returns:
        str: JSON object with schematic component data for requested designators
    """
    logger.info(f"Getting schematic data for components: {cmp_designators}")
    
    # Execute the command in Altium to get schematic data
    response = await altium_bridge.execute_command(
        "get_schematic_data",
        {}  # No parameters needed for this command in the Altium script
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting schematic data: {error_msg}")
        return json.dumps({"error": f"Failed to get schematic data: {error_msg}"})
    
    # Get the schematic data
    schematic_data = response.get("result", [])
    
    if not schematic_data:
        logger.info("No schematic data found")
        return json.dumps({"error": "No schematic data found"})
    
    try:
        # Parse the data if it's a string
        if isinstance(schematic_data, str):
            schematic_list = json.loads(schematic_data)
        else:
            schematic_list = schematic_data
        
        # Filter components by designator
        components = []
        missing_designators = []
        
        for designator in cmp_designators:
            found = False
            for component in schematic_list:
                if component.get("designator") == designator:
                    components.append(component)
                    found = True
                    break
            
            if not found:
                missing_designators.append(designator)
        
        result = {
            "components": components,
        }
        
        if missing_designators:
            result["missing_designators"] = missing_designators
            logger.info(f"Some designators not found in schematic data: {missing_designators}")
        
        logger.info(f"Found schematic data for {len(components)} components")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error processing schematic data: {e}")
        return json.dumps({"error": f"Failed to process schematic data: {str(e)}"})
    
@mcp.tool()
async def get_pcb_layers(ctx: Context) -> str:
    """
    Get detailed information about all layers in the current Altium PCB
    
    Returns:
        str: JSON object with detailed layer information including copper layers, 
             mechanical layers, and special layers with their properties
    """
    logger.info("Getting detailed PCB layer information")
    
    # Execute the command in Altium to get all layers data
    response = await altium_bridge.execute_command(
        "get_pcb_layers",
        {}  # No parameters needed
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting PCB layers: {error_msg}")
        return json.dumps({"error": f"Failed to get PCB layers: {error_msg}"})
    
    # Get the layers data
    layers_data = response.get("result", [])
    
    if not layers_data:
        logger.info("No PCB layers found")
        return json.dumps({"message": "No PCB layers found in the current document"})
    
    logger.info(f"Retrieved PCB layers data")
    return json.dumps(layers_data, indent=2)

@mcp.tool()
async def set_pcb_layer_visibility(ctx: Context, layer_names: list, visible: bool) -> str:
    """
    Set visibility for specified PCB layers
    
    Args:
        layer_names (list): List of layer names to modify (e.g., ["Top Layer", "Bottom Layer", "Mechanical 1"])
        visible (bool): Whether to show (True) or hide (False) the specified layers
        
    Returns:
        str: JSON object with the result of the operation
    """
    logger.info(f"Setting layers visibility: {layer_names} to {visible}")
    
    # Execute the command in Altium to set layer visibility
    response = await altium_bridge.execute_command(
        "set_pcb_layer_visibility",
        {
            "layer_names": layer_names,
            "visible": visible
        }
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error setting layer visibility: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to set layer visibility: {error_msg}"})
    
    # Get the result data
    result = response.get("result", {})
    
    logger.info(f"Layer visibility set successfully")
    return json.dumps(result, indent=2)

@mcp.tool()
async def get_component_data(ctx: Context, cmp_designators: list) -> str:
    """
    Get all data for components in Altium
    
    Args:
        cmp_designators (list): List of designators of the components (e.g., ["R1", "C5", "U3"])
    
    Returns:
        str: JSON object with all component data for requested designators
    """
    logger.info(f"Getting data for components: {cmp_designators}")
    
    # Execute the command in Altium to get all component data
    response = await altium_bridge.execute_command(
        "get_all_component_data",
        {}  # No parameters needed for this command in the Altium script
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting component data: {error_msg}")
        return json.dumps({"error": f"Failed to get component data: {error_msg}"})
    
    # Get the component data
    component_data = response.get("result", [])
    
    if not component_data:
        logger.info("No component data found")
        return json.dumps({"error": "No component data found"})
    
    try:
        # Parse the data if it's a string
        if isinstance(component_data, str):
            component_list = json.loads(component_data)
        else:
            component_list = component_data
        
        # Filter components by designator
        components = []
        missing_designators = []
        
        for designator in cmp_designators:
            found = False
            for component in component_list:
                if component.get("designator") == designator:
                    components.append(component)
                    found = True
                    break
            
            if not found:
                missing_designators.append(designator)
        
        result = {
            "components": components,
        }
        
        if missing_designators:
            result["missing_designators"] = missing_designators
            logger.info(f"Some designators not found: {missing_designators}")
        
        logger.info(f"Found data for {len(components)} components")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error processing component data: {e}")
        return json.dumps({"error": f"Failed to process component data: {str(e)}"})

@mcp.tool()
async def get_selected_components_coordinates(ctx: Context) -> str:
    """
    Get coordinates and positioning information for selected components in Altium layout
    
    Returns:
        str: JSON array with positioning data (designator, x, y, rotation, width, height)
    """
    logger.info("Getting coordinates for selected components")
    
    # Execute the command in Altium to get selected components coordinates
    response = await altium_bridge.execute_command(
        "get_selected_components_coordinates",
        {}  # No parameters needed
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting selected components coordinates: {error_msg}")
        return json.dumps({"error": f"Failed to get selected components coordinates: {error_msg}"})
    
    # Get the components coordinates data
    components_coords = response.get("result", [])
    
    if not components_coords:
        logger.info("No selected components found")
        return json.dumps({"message": "No components are currently selected in the layout"})
    
    logger.info(f"Retrieved positioning data for selected components")
    return json.dumps(components_coords, indent=2)

@mcp.tool()
async def get_all_designators(ctx: Context) -> str:
    """
    Get all component designators from the current Altium board
    
    Returns:
        str: JSON array of all component designators on the current board
    """
    logger.info("Getting all component designators")
    
    # Execute the command in Altium to get all component data
    response = await altium_bridge.execute_command(
        "get_all_component_data",
        {}  # No parameters needed
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting component data: {error_msg}")
        return json.dumps({"error": f"Failed to get component data: {error_msg}"})
    
    # Get the component data
    component_data = response.get("result", [])
    
    if not component_data:
        logger.info("No component data found")
        return json.dumps({"error": "No component data found"})
    
    try:
        # Parse the data if it's a string
        if isinstance(component_data, str):
            component_list = json.loads(component_data)
        else:
            component_list = component_data
        
        # Extract designators
        designators = [comp.get("designator") for comp in component_list if "designator" in comp]
        
        logger.info(f"Found {len(designators)} designators")
        return json.dumps(designators)
    except Exception as e:
        logger.error(f"Error processing component data: {e}")
        return json.dumps({"error": f"Failed to process component data: {str(e)}"})

@mcp.tool()
async def get_component_pins(ctx: Context, cmp_designators: list) -> str:
    """
    Get pin data for components in Altium
    
    Args:
        cmp_designators (list): List of designators of the components (e.g., ["R1", "C5", "U3"])
    
    Returns:
        str: JSON object with pin data for requested designators
    """
    logger.info(f"Getting pin data for components: {cmp_designators}")
    
    # Execute the command in Altium to get pin data
    response = await altium_bridge.execute_command(
        "get_component_pins",
        {"designators": cmp_designators}  # Pass the list of designators
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting pin data: {error_msg}")
        return json.dumps({"error": f"Failed to get pin data: {error_msg}"})
    
    # Get the components pins data
    pins_data = response.get("result", [])
    
    if not pins_data:
        logger.info(f"No pin data found for designators: {cmp_designators}")
        return json.dumps({"message": "No pin data found for the specified components"})
    
    logger.info(f"Retrieved pin data for components")
    return json.dumps(pins_data, indent=2)

@mcp.tool()
async def get_all_nets(ctx: Context) -> str:
    """
    Return every unique net name in the active PCB document.

    Returns
    -------
    str :
        A JSON array of net names, e.g. ["GND", "VCC33", "USB_D+", ...]
    """
    logger.info("Getting all nets")

    response = await altium_bridge.execute_command("get_all_nets", {})

    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting nets: {error_msg}")
        return json.dumps({"error": f"Failed to get nets: {error_msg}"})

    # Result is already a JSON‑serialisable Python list
    return json.dumps(response.get("result", []), indent=2)

@mcp.tool()
async def create_net_class(ctx: Context, class_name: str, net_names: list) -> str:
    """
    Create a new net class and add specified nets to it
    
    Args:
        class_name (str): Name of the net class to create or modify
        net_names (list): List of net names to add to the class
    
    Returns:
        str: JSON object with the result of the operation
    """
    logger.info(f"Creating net class '{class_name}' with {len(net_names)} nets")
    
    # Execute the command in Altium to create the net class
    response = await altium_bridge.execute_command(
        "create_net_class",
        {
            "class_name": class_name,
            "net_names": net_names
        }
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error creating net class: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to create net class: {error_msg}"})
    
    # Get the result data
    result = response.get("result", {})
    
    logger.info(f"Net class '{class_name}' created/modified successfully")
    return json.dumps(result, indent=2)
    
@mcp.tool()
async def set_component_position(ctx: Context, cmp_designator: str, x: float, y: float, rotation: float = -1) -> str:
    """
    Set a component's absolute position in the PCB layout
    
    Args:
        cmp_designator (str): Designator of the component to position (e.g., "R1", "C5", "U3")
        x (float): Absolute X position in mils
        y (float): Absolute Y position in mils
        rotation (float): Rotation angle in degrees (0-360), use -1 to keep current rotation
    
    Returns:
        str: JSON object with the result of the position operation
    """
    logger.info(f"Setting component {cmp_designator} position to X:{x}, Y:{y}, Rotation:{rotation}")
    
    response = await altium_bridge.execute_command(
        "set_component_position",
        {
            "designator": cmp_designator,
            "x": x,
            "y": y,
            "rotation": rotation
        }
    )
    
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error setting component position: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to set component position: {error_msg}"})
    
    result = response.get("result", {})
    logger.info(f"Component position set successfully")
    return json.dumps({"success": True, "result": result}, indent=2)

@mcp.tool()
async def move_components(ctx: Context, cmp_designators: list, x_offset: float, y_offset: float, rotation: float = 0) -> str:
    """
    Move components by RELATIVE offset from their current position (not absolute positioning)
    
    IMPORTANT: This moves components BY the offset amount, not TO a position.
    For absolute positioning, use set_component_position instead.
    
    Args:
        cmp_designators (list): List of designators of the components to move (e.g., ["R1", "C5", "U3"])
        x_offset (float): X offset distance in mils (positive = right, negative = left)
        y_offset (float): Y offset distance in mils (positive = up, negative = down)
        rotation (float): New absolute rotation angle in degrees (0-360), if 0 the rotation is not changed
    
    Returns:
        str: JSON object with the result of the move operation
    """
    logger.info(f"Moving components: {cmp_designators} by X:{x_offset}, Y:{y_offset}, Rotation:{rotation}")
    
    # Execute the command in Altium to move components
    response = await altium_bridge.execute_command(
        "move_components",
        {
            "designators": cmp_designators,
            "x_offset": x_offset,
            "y_offset": y_offset,
            "rotation": rotation
        }
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error moving components: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to move components: {error_msg}"})
    
    # Get the result data
    result = response.get("result", {})
    
    logger.info(f"Components moved successfully")
    return json.dumps({"success": True, "result": result}, indent=2)

@mcp.tool()
async def get_screenshot(ctx: Context, view_type: str = "pcb") -> str:
    """
    Take a screenshot of the Altium window
    
    Args:
        view_type (str): Type of view to capture - 'pcb' or 'sch'
    
    Returns:
        str: JSON object with screenshot data (base64 encoded) and metadata
    """
    logger.info(f"Taking screenshot of Altium {view_type} window")
    
    try:
        # First, execute the Altium command to ensure the right document type is focused
        response = await altium_bridge.execute_command(
            "take_view_screenshot", 
            {"view_type": view_type.lower()}
        )
        
        # Check for success
        if not response.get("success", False):
            error_msg = response.get("error", "Unknown error")
            logger.error(f"Error focusing {view_type} document: {error_msg}")
            return json.dumps({"success": False, "error": f"Failed to focus the correct document type: {error_msg}"})
        
        # Run the screenshot capture in a separate thread
        import threading
        import queue
        import datetime
        from PIL import Image
        
        result_queue = queue.Queue()
        
        def capture_screenshot_thread():
            try:
                # Find Altium windows
                altium_windows = []
                altium_fallback_windows = []
                
                def collect_altium_windows(hwnd, _):
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        
                        # First, look for windows with Altium and .PrjPcb in the title
                        if "Altium" in title and ".PrjPcb" in title:
                            altium_windows.append({
                                "handle": hwnd,
                                "title": title,
                                "class_name": win32gui.GetClassName(hwnd),
                                "rect": win32gui.GetWindowRect(hwnd)
                            })
                        # Collect any window with Altium in the title as fallback
                        elif "Altium" in title:
                            altium_fallback_windows.append({
                                "handle": hwnd,
                                "title": title,
                                "class_name": win32gui.GetClassName(hwnd),
                                "rect": win32gui.GetWindowRect(hwnd)
                            })
                    return True
                
                win32gui.EnumWindows(collect_altium_windows, 0)
                
                # If no specific Altium .PrjPcb windows found, use the fallback
                if not altium_windows and altium_fallback_windows:
                    altium_windows = altium_fallback_windows
                
                if not altium_windows:
                    result_queue.put({
                        "success": False, 
                        "error": f"No Altium windows found for {view_type} view"
                    })
                    return
                
                # Use the first matching window
                window = altium_windows[0]
                hwnd = window["handle"]
                
                # Get window dimensions
                left, top, right, bottom = window["rect"]
                width = right - left
                height = bottom - top
                
                if width <= 0 or height <= 0:
                    result_queue.put({"success": False, "error": f"Invalid window dimensions: {width}x{height}"})
                    return
                
                # Try to activate the window
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Could not bring window to foreground: {e}")
                
                # Take screenshot using GDI functions instead of ImageGrab
                try:
                    # Get device context
                    hwndDC = win32gui.GetWindowDC(hwnd)
                    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
                    saveDC = mfcDC.CreateCompatibleDC()
                    
                    # Create a bitmap object
                    saveBitMap = win32ui.CreateBitmap()
                    saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
                    saveDC.SelectObject(saveBitMap)
                    
                    # Copy the screen into the bitmap
                    saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0), win32con.SRCCOPY)
                    
                    # Convert the bitmap to an Image
                    bmpinfo = saveBitMap.GetInfo()
                    bmpstr = saveBitMap.GetBitmapBits(True)
                    img = Image.frombuffer(
                        'RGB',
                        (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                        bmpstr, 'raw', 'BGRX', 0, 1)
                    
                    # Save a local copy of the screenshot for debugging (non-fatal if it fails)
                    try:
                        debug_filename = str(MCP_DIR / f"screenshot_{view_type}.png")
                        img.save(debug_filename)
                        logger.info(f"Saved debug screenshot to {debug_filename}")
                    except Exception as save_error:
                        logger.warning(f"Could not save debug screenshot to {debug_filename}: {save_error}")
                        debug_filename = None  # Clear it since save failed
                    
                    # Clean up GDI resources
                    win32gui.DeleteObject(saveBitMap.GetHandle())
                    saveDC.DeleteDC()
                    mfcDC.DeleteDC()
                    win32gui.ReleaseDC(hwnd, hwndDC)
                    
                    # Convert to base64
                    buffer = io.BytesIO()
                    img.save(buffer, format='PNG')
                    buffer.seek(0)
                    img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
                    
                    # Put result in queue
                    result_queue.put({
                        "success": True,
                        "width": width,
                        "height": height,
                        "window_title": window["title"],
                        "window_class": window["class_name"],
                        "view_type": view_type,
                        "image_format": "PNG",
                        "encoding": "base64",
                        "debug_file": debug_filename,
                        "image_data": img_base64
                    })
                    
                except Exception as e:
                    import traceback
                    trace = traceback.format_exc()
                    logger.error(f"GDI screenshot error: {e}\n{trace}")
                    result_queue.put({
                        "success": False, 
                        "error": f"GDI screenshot failed: {str(e)}",
                        "traceback": trace
                    })
                
            except Exception as e:
                import traceback
                result_queue.put({
                    "success": False, 
                    "error": f"Screenshot thread error: {str(e)}",
                    "traceback": traceback.format_exc()
                })
        
        # Start the thread
        thread = threading.Thread(target=capture_screenshot_thread)
        thread.daemon = True
        thread.start()
        
        # Wait for the thread to complete
        thread.join(timeout=10)  # 10 second timeout
        
        if thread.is_alive():
            logger.error("Screenshot thread timed out")
            return json.dumps({"success": False, "error": "Screenshot operation timed out"})
        
        # Get the result from the queue
        if result_queue.empty():
            logger.error("Screenshot thread did not return a result")
            return json.dumps({"success": False, "error": "Screenshot thread did not return a result"})
        
        result = result_queue.get()
        
        if not result.get("success", False):
            error_msg = result.get("error", "Unknown error")
            logger.error(f"Screenshot error: {error_msg}")
            return json.dumps({"success": False, "error": error_msg})
        
        logger.info(f"Screenshot taken successfully, size: {result['width']}x{result['height']}")
        return json.dumps(result)
    
    except Exception as e:
        logger.error(f"Error in screenshot function: {str(e)}")
        return json.dumps({"success": False, "error": f"Failed to take screenshot: {str(e)}"})
    
@mcp.tool()
async def layout_duplicator(ctx: Context) -> str:
    """
    First step of layout duplication. Selects source components and returns data to match with destination components.
    
    Returns:
        str: JSON object with source and destination component data for matching
    """
    logger.info("Starting layout duplication - selection phase")
    
    # Execute the command in Altium to get component data
    response = await altium_bridge.execute_command(
        "layout_duplicator", 
        {}
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error in layout duplication selection: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to start layout duplication: {error_msg}"})
    
    # Get the component data
    components_data = response.get("result", {})
    
    if not components_data:
        logger.info("No component data found")
        return json.dumps({"success": False, "error": "No component data returned from Altium"})
    
    # Parse the result to check if no source components were selected
    try:
        if isinstance(components_data, str):
            result_json = json.loads(components_data)
            if not result_json.get("success", True):
                logger.info(f"Source component selection issue: {result_json.get('message', 'Unknown issue')}")
                return json.dumps(result_json)
    except Exception as e:
        logger.error(f"Error parsing layout duplicator result: {e}")
    
    logger.info(f"Retrieved layout duplicator component data")
    return json.dumps(components_data, indent=2)

@mcp.tool()
async def layout_duplicator_apply(ctx: Context, source_designators: list, destination_designators: list) -> str:
    """
    Second step of layout duplication. Applies the layout of source components to destination components.
    
    Args:
        source_designators (list): List of source component designators (e.g., ["R1", "C5", "U3"])
        destination_designators (list): List of destination component designators (e.g., ["R10", "C15", "U7"])
    
    Returns:
        str: JSON object with the result of the layout duplication
    """
    logger.info(f"Applying layout duplication from {source_designators} to {destination_designators}")
    
    # Execute the command in Altium to apply layout duplication
    response = await altium_bridge.execute_command(
        "layout_duplicator_apply",
        {
            "source_designators": source_designators,
            "destination_designators": destination_designators
        }
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error applying layout duplication: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to apply layout duplication: {error_msg}"})
    
    # Get the result data
    result = response.get("result", {})
    
    logger.info(f"Layout duplication applied successfully")
    return json.dumps(result, indent=2)
    
@mcp.tool()
async def get_pcb_rules(ctx: Context) -> str:
    """
    Get all design rules from the current Altium PCB
    
    Returns:
        str: JSON array of PCB design rules with their properties
    """
    logger.info("Getting PCB design rules")
    
    # Execute the command in Altium to get rule data
    response = await altium_bridge.execute_command(
        "get_pcb_rules",
        {}  # No parameters needed
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting PCB rules: {error_msg}")
        return json.dumps({"error": f"Failed to get PCB rules: {error_msg}"})
    
    # Get the rules data
    rules_data = response.get("result", [])
    
    if not rules_data:
        logger.info("No PCB rules found")
        return json.dumps({"message": "No PCB rules found in the current document"})
    
    logger.info(f"Retrieved PCB rules data")
    return json.dumps(rules_data, indent=2)

@mcp.tool()
async def get_pcb_layer_stackup(ctx: Context) -> str:
    """
    Get the detailed layer stackup information from the current Altium PCB including
    copper thickness, dielectric materials, constants, and heights
    
    Returns:
        str: JSON object with detailed layer stackup information
    """
    logger.info("Getting PCB layer stackup information")
    
    # Execute the command in Altium to get layer stackup data
    response = await altium_bridge.execute_command(
        "get_pcb_layer_stackup",
        {}  # No parameters needed
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting PCB layer stackup: {error_msg}")
        return json.dumps({"error": f"Failed to get PCB layer stackup: {error_msg}"})
    
    # Get the stackup data
    stackup_data = response.get("result", {})
    
    if not stackup_data:
        logger.info("No PCB layer stackup found")
        return json.dumps({"message": "No PCB layer stackup found in the current document"})
    
    logger.info(f"Retrieved PCB layer stackup data")
    return json.dumps(stackup_data, indent=2)

@mcp.tool()
async def get_output_job_containers(ctx: Context) -> str:
    """
    Get all available output job containers from a specified OutJob file
    
    Args:
        outjob_path (str): Path to the OutJob file (optional, will use first open OutJob if not provided)
    
    Returns:
        str: JSON array with all output job containers and their properties
    """
    logger.info("Getting output job containers from the first open OutJob")
    
    # Execute the command in Altium to get output job containers
    response = await altium_bridge.execute_command(
        "get_output_job_containers", 
        {}  # No parameters needed - will use first open OutJob
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error getting output job containers: {error_msg}")
        return json.dumps({"error": f"Failed to get output job containers: {error_msg}"})
    
    # Get the containers data
    containers_data = response.get("result", [])
    
    if not containers_data:
        logger.info("No output job containers found")
        return json.dumps({"message": "No output job containers found"})
    
    logger.info(f"Retrieved output job containers data")
    return containers_data  # Already in JSON format

@mcp.tool()
async def run_output_jobs(ctx: Context, container_names: list) -> str:
    """
    Run specified output job containers
    
    Args:
        container_names (list): List of container names to run
    
    Returns:
        str: JSON object with results of running the output jobs
    """
    logger.info(f"Running output jobs")
    logger.info(f"Containers to run: {container_names}")
    
    # Execute the command in Altium to run output jobs
    response = await altium_bridge.execute_command(
        "run_output_jobs", 
        {"container_names": container_names}
    )
    
    # Check for success
    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error running output jobs: {error_msg}")
        return json.dumps({"error": f"Failed to run output jobs: {error_msg}"})
    
    # Get the result data
    result_data = response.get("result", {})
    
    logger.info(f"Output jobs execution completed")
    
    # If result_data is a string, it's already in JSON format
    if isinstance(result_data, str):
        return result_data
    
    # Otherwise, convert to JSON
    return json.dumps(result_data, indent=2)

@mcp.tool()
async def create_pcb_footprint(ctx: Context, footprint_name: str, description: str, pads: list, courtyard_x_mm: float = 0, courtyard_y_mm: float = 0) -> str:
    """
    Create a new PCB footprint in the currently active PcbLib document.
    The PcbLib (e.g. Discrete.PcbLib) must be the focused document in Altium.

    Pad format: each element is "pad_number|x_mm|y_mm|width_mm|height_mm|shape"
                shape options: Rect (default), Round, Oval
                Coordinates are in mm relative to component origin (0,0).
                Pin 1 is indicated by a gap in the top-left silkscreen corner.

    Courtyard & silkscreen are auto-generated from pad extents + 0.25 mm margin
    unless courtyard_x_mm / courtyard_y_mm are provided explicitly (half-dimensions).

    Args:
        footprint_name (str): Footprint name as it will appear in the library
        description (str): Description string
        pads (list): List of pad definitions, e.g. ["1|-0.9|0.55|1.0|0.8|Rect", ...]
        courtyard_x_mm (float): Half-width of courtyard in mm (0 = auto)
        courtyard_y_mm (float): Half-height of courtyard in mm (0 = auto)

    Returns:
        str: JSON object with result
    """
    logger.info(f"Creating PCB footprint: {footprint_name} with {len(pads)} pads")

    response = await altium_bridge.execute_command(
        "create_pcb_footprint",
        {
            "footprint_name": footprint_name,
            "description": description,
            "pads": pads,
            "courtyard_x_mm": courtyard_x_mm,
            "courtyard_y_mm": courtyard_y_mm,
        }
    )

    if not response.get("success", False):
        error_msg = response.get("error", "Unknown error")
        logger.error(f"Error creating footprint: {error_msg}")
        return json.dumps({"success": False, "error": f"Failed to create footprint: {error_msg}"})

    result = response.get("result", {})
    logger.info(f"Footprint {footprint_name} created successfully")
    return json.dumps(result, indent=2)

@mcp.tool()
async def get_server_status(ctx: Context) -> str:
    """Get the current status of the Altium MCP server"""
    status = {
        "server": "Running",
        "altium_exe": altium_bridge.config.altium_exe_path,
        "script_path": altium_bridge.config.script_path,
        "altium_found": os.path.exists(altium_bridge.config.altium_exe_path),
        "script_found": os.path.exists(altium_bridge.config.script_path),
    }
    
    return json.dumps(status, indent=2)

if __name__ == "__main__":
    logger.info("Starting Altium MCP Server...")
    logger.info(f"Using MCP directory: {MCP_DIR}")
    
    # Initialize the directory
    MCP_DIR.mkdir(exist_ok=True)
    
    # Create the AltiumScript directory if it doesn't exist
    script_dir = MCP_DIR / "AltiumScript"
    script_dir.mkdir(exist_ok=True)
    
    # Verify configuration before starting
    if not altium_bridge.config.verify_paths():
        print("Warning: Configuration not complete. Some functionality may not work.")
    
    # Print status
    print(f"Altium executable: {altium_bridge.config.altium_exe_path}")
    print(f"Script path: {altium_bridge.config.script_path}")
    
    # Run the server
    mcp.run(transport='stdio')