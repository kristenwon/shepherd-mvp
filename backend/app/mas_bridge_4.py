#deployment ver 
import asyncio
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dotenv import load_dotenv

load_dotenv()

# Configuration for MAS repository
MAS_REPO_PATH = os.environ.get("MAS_REPO_PATH", "../blackRabbit")
MAS_PYTHON_PATH = os.environ.get("MAS_PYTHON_PATH", "python")

# Global state for tracking output patterns
class PromptDetector:
    def __init__(self):
        self.recent_lines = []  # Keep track of recent output
        self.max_history = 10
        self.last_input_time = 0
        self.pending_prompt = None
        self.seen_prompts = set()  # Remember prompts we've seen
        self.waiting_for_multiline = False
        self.multiline_empty_count = 0
        self.detected_prompts = set()  # Track prompts we've detected for filtering
        
    def add_line(self, line: str):
        """Add a line to history"""
        self.recent_lines.append(line)
        if len(self.recent_lines) > self.max_history:
            self.recent_lines.pop(0)
    
    def is_progress_output(self, line: str) -> bool:
        """Check if this looks like progress/status output"""
        line_lower = line.lower().strip()
        
        # Common progress indicators
        progress_patterns = [
            r'\d+%',  # Percentage
            r'\[\d+/\d+\]',  # [1/10] style progress
            r'\(\d+/\d+\)',  # (1/10) style progress
            r'\.{3,}',  # Multiple dots ...
            r'\s{2,}\d+\s{2,}',  # Spaced numbers
            r'[│├└─═║╔╗╚╝]',  # Box drawing characters
            r'^\s*\*+\s*$',  # Lines of asterisks
            r'^\s*-+\s*$',  # Lines of dashes
            r'^\s*=+\s*$',  # Lines of equals
        ]
        
        # Check regex patterns
        for pattern in progress_patterns:
            if re.search(pattern, line):
                return True
        
        # Check for specific keywords that indicate progress
        progress_keywords = [
            'remote:', 'counting', 'compressing', 'receiving', 'resolving',
            'unpacking', 'checking', 'updating', 'downloading', 'uploading',
            'processing', 'installing', 'building', 'compiled', 'linking',
            'bytes', 'objects', 'deltas', 'done', 'complete', 'finished',
            'progress', 'status', 'info:', 'debug:', 'trace:', 'warn:',
            'writing', 'reading', 'loading', 'saving', 'fetching'
        ]
        
        for keyword in progress_keywords:
            if keyword in line_lower:
                return True
        
        return False
    
    # Add these patterns to your PromptDetector class

    def is_likely_prompt(self, line: str) -> bool:
        """Check if this line is likely a prompt for user input"""
        if not line or len(line) > 300:
            return False
        
        line_lower = line.lower().strip()
        
        if "press enter twice" in line_lower:
            return False
        
        line_stripped = line.strip()
        if not line_stripped:
            return False
        
        # First, exclude progress output
        if self.is_progress_output(line):
            return False
        
        # Check if it's a repeat of a prompt we've already answered
        if line_stripped in self.seen_prompts:
            return False
        
        # Look for specific MAS prompts (your custom prompts)
        mas_prompt_patterns = [
            r'Enter the contract name.*:$',  # Your contract name prompt
            r'Enter the specific function.*:$',  # Your function prompt
            r'Enter hypothesis.*:$',  # Your hypothesis prompt
            r'Enter your detailed vulnerability hypothesis.*:$',  # Your detailed prompt
            r'\nRun another MAS\?.*:$',  # NEW: Catch "Run another MAS? (y/N):" prompt
        ]
        
        # Check MAS-specific patterns first
        for pattern in mas_prompt_patterns:
            if re.search(pattern, line_stripped, re.IGNORECASE):
                return True
        
        # Check for yes/no prompts specifically
        yes_no_patterns = [
            r'.*\(y/n\)\s*:?\s*$',  # Matches (y/n) at end
            r'.*\(Y/N\)\s*:?\s*$',  # Matches (Y/N) at end
            r'.*\(yes/no\)\s*:?\s*$',  # Matches (yes/no) at end
            r'.*\[y/n\]\s*:?\s*$',  # Matches [y/n] at end
            r'.*\[Y/N\]\s*:?\s*$',  # Matches [Y/N] at end
        ]
        
        for pattern in yes_no_patterns:
            if re.search(pattern, line_stripped, re.IGNORECASE):
                return True
        
        # Look for general question patterns
        question_patterns = [
            r'^.*\?\s*$',  # Ends with ?
            r'^.*:\s*$',   # Ends with :
            r'^>\s*',      # Starts with >
            r'^>>>\s*',    # Python-style prompt
            r'^\$\s*',     # Shell prompt
            r'^Enter\s+',  # Starts with Enter
            r'^Please\s+', # Starts with Please
            r'^Provide\s+', # Starts with Provide
            r'^Select\s+', # Starts with Select
            r'^Choose\s+', # Starts with Choose
            r'^Type\s+',   # Starts with Type
            r'^Input\s+',  # Starts with Input
            r'^What\s+',   # Starts with What
            r'^Which\s+',  # Starts with Which
            r'^Do you\s+', # Starts with Do you
            r'^Would you\s+', # Starts with Would you
            r'^Specify\s+', # Starts with Specify
            r'^Run\s+',    # NEW: Starts with Run
            r'^Continue\s+', # NEW: Starts with Continue
            r'^Restart\s+', # NEW: Starts with Restart
        ]
        
        # Check patterns
        for pattern in question_patterns:
            if re.match(pattern, line_stripped, re.IGNORECASE):
                # Additional validation
                # Make sure it's not just a colon after numbers or progress
                if line_stripped.endswith(':'):
                    text_before = line_stripped[:-1].strip()
                    # Avoid matching "Step 1:" or "100%:" etc
                    if re.match(r'^(Step\s+)?\d+$', text_before) or re.match(r'^\d+%$', text_before):
                        return False
                    # But DO match prompts with parentheses
                    if "enter" in text_before.lower() or "input" in text_before.lower() or "run" in text_before.lower():
                        return True
                return True
        
        return False
    
    def should_wait_for_input(self, current_line: str, time_since_last_char: float) -> bool:
        """Determine if we should wait for user input"""
        if not current_line:
            return False
        
        # Special case: Check if the recent output contains setup/header text
        # that typically precedes prompts
        setup_indicators = [
            "ANALYSIS SETUP",
            "VULNERABILITY HYPOTHESIS",
            "Let's focus on",
            "============"
        ]
        
        has_setup_context = any(
            any(indicator in line for indicator in setup_indicators) 
            for line in self.recent_lines[-5:]
        )
        
        # Special case: Check for hypothesis instructions that indicate silent input wait
        hypothesis_indicators = [
            "Enter hypothesis (press Enter twice when done):",
            "Enter your detailed vulnerability hypothesis",
            "(press Enter twice when done)"
        ]
        
        # Check if we just saw hypothesis instructions
        for line in self.recent_lines[-3:]:
            for indicator in hypothesis_indicators:
                if indicator in line:
                    # MAS is now silently waiting for hypothesis input
                    return True
        
        # If we haven't seen output for a bit and the line looks like a prompt
        if time_since_last_char > 0.3 and self.is_likely_prompt(current_line):
            # If we have setup context, be more aggressive about detecting prompts
            if has_setup_context:
                return True
                
            # Otherwise use normal detection
            if len(self.recent_lines) >= 2:
                # If the last few lines were all progress, this probably isn't a real prompt
                recent_progress_count = sum(1 for line in self.recent_lines[-3:] 
                                          if self.is_progress_output(line))
                if recent_progress_count >= 2:
                    return False
            return True
        
        return False

# Add this class before launch_mas_interactive
class OutputBuffer:
    """Smart buffer that holds back potential prompts"""
    def __init__(self, ws_manager, run_id, detector):
        self.ws_manager = ws_manager
        self.run_id = run_id
        self.detector = detector
        self.buffer = ""
        self.hold_buffer = ""  # Buffer for holding potential prompts
        self.last_newline_sent = True
        
# In the OutputBuffer class, update the add_char method:

    async def add_char(self, char: str):
        """Add a character and manage buffering"""
        self.buffer += char
        
        if char == '\n':
            # We have a complete line
            line = self.buffer.strip()
            
            # Special check for the "Run another MAS?" prompt
            # This prompt might come after a newline, so check recent context
            run_another_patterns = [
                "run another mas?",
                "▶️  run another mas?",
                "▶  run another mas?",  # Without emoji variant selector
                "run another mas? (y/n)",
            ]
            
            is_run_another_prompt = any(
                pattern in line.lower() for pattern in run_another_patterns
            )
            
            # Special check for hypothesis prompts and related lines
            hypothesis_patterns = [
                "Enter hypothesis (press Enter twice when done):",
                "Enter your detailed vulnerability hypothesis",
                "Example: 'This function allows",
                "Example:",
                "(2-3 lines):",
            ]
            
            # Also check if this is part of a multi-line prompt sequence
            is_hypothesis_related = any(pattern in line for pattern in hypothesis_patterns)
            
            # Check if recent lines contained hypothesis prompt indicators
            recent_has_hypothesis = False
            if len(self.detector.recent_lines) > 0:
                for recent in self.detector.recent_lines[-3:]:
                    if any(pattern in recent for pattern in ["Enter hypothesis", "vulnerability hypothesis"]):
                        recent_has_hypothesis = True
                        break
            
            # If this line is a prompt, hold it
            if (self.detector.is_likely_prompt(line) or 
                is_hypothesis_related or 
                is_run_another_prompt or  # Added this condition
                (recent_has_hypothesis and line.startswith("Example:"))):
                # Hold this line - don't send it yet
                self.hold_buffer = self.buffer
                self.buffer = ""
                return
            else:
                # Not a prompt, send any held buffer first
                if self.hold_buffer:
                    await self._send(self.hold_buffer)
                    self.hold_buffer = ""
                
                # Send current buffer
                await self._send(self.buffer)
                self.buffer = ""
                self.last_newline_sent = True
        else:
            # Still building a line
            self.last_newline_sent = False
            
            # Check if we're building the "Run another MAS?" prompt
            # This prompt might come character by character
            buffer_lower = self.buffer.lower()
            if ("run another mas" in buffer_lower or "▶" in self.buffer):
                # We might be building this prompt, don't send yet
                return
            
            # If buffer is getting large and we have no held content, send it
            if len(self.buffer) > 200 and not self.hold_buffer:
                await self._send(self.buffer)
                self.buffer = ""
    
    async def flush_if_not_prompt(self):
        """Flush buffers if they don't contain prompts"""
        if self.hold_buffer:
            # We were holding a potential prompt
            line = self.hold_buffer.strip()
            
            # Special check for hypothesis prompts
            hypothesis_patterns = [
                "Enter hypothesis (press Enter twice when done):",
                "Enter your detailed vulnerability hypothesis"
            ]
            
            is_hypothesis_prompt = any(pattern in line for pattern in hypothesis_patterns)
            
            if not self.detector.is_likely_prompt(line) and not is_hypothesis_prompt:
                # False alarm, send it
                await self._send(self.hold_buffer)
            self.hold_buffer = ""
        
        if self.buffer:
            line = self.buffer.strip()
            hypothesis_patterns = [
                "Enter hypothesis (press Enter twice when done):",
                "Enter your detailed vulnerability hypothesis"
            ]
            
            is_hypothesis_prompt = any(pattern in line for pattern in hypothesis_patterns)
            
            if not self.detector.is_likely_prompt(line) and not is_hypothesis_prompt:
                await self._send(self.buffer)
                self.buffer = ""
    
    def clear_prompt(self):
        """Clear held prompt buffer when we confirm it's a prompt"""
        self.hold_buffer = ""
        self.buffer = ""
    
    async def force_flush(self):
        """Force send all buffers"""
        if self.hold_buffer:
            await self._send(self.hold_buffer)
            self.hold_buffer = ""
        if self.buffer:
            await self._send(self.buffer)
            self.buffer = ""
    
    async def _send(self, data: str):
        """Send data via WebSocket"""
        if data and self.ws_manager:
            # Apply sensitive content filtering here
            filtered_data = self._filter_sensitive_content(data)
            if filtered_data:
                await self.ws_manager.send_log(self.run_id, {
                    "type": "output",
                    "data": filtered_data
                })
    
    def _filter_sensitive_content(self, text):
        """Filter out lines containing sensitive information"""
        FILTER_PATTERNS = [
            r'API_KEY:\s*[a-zA-Z0-9\-_]{20,}'
        ]
        
        lines = text.split('\n')
        filtered_lines = []
        
        for line in lines:
            # Check if this line should be filtered
            should_filter = False
            for pattern in FILTER_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    should_filter = True
                    break
            
            if not should_filter:
                filtered_lines.append(line)
        
        # Reconstruct the text, preserving newlines
        result = '\n'.join(filtered_lines)
        
        # Handle edge case where original text ended with newline
        if text.endswith('\n') and not result.endswith('\n'):
            result += '\n'
        
        return result

# Add this class before launch_mas_interactive
class OutputBuffer:
    """Smart buffer that holds back potential prompts"""
    def __init__(self, ws_manager, run_id, detector):
        self.ws_manager = ws_manager
        self.run_id = run_id
        self.detector = detector
        self.buffer = ""
        self.hold_buffer = ""  # Buffer for holding potential prompts
        self.last_newline_sent = True
        
    async def add_char(self, char: str):
        """Add a character and manage buffering"""
        self.buffer += char
        
        if char == '\n':
            # We have a complete line
            line = self.buffer.strip()
            
            # Special check for hypothesis prompts and related lines
            hypothesis_patterns = [
                "Enter hypothesis (press Enter twice when done):",
                "Enter your detailed vulnerability hypothesis",
                "Example: 'This function allows",  # The example line
                "Example:",  # Any example line
                "(2-3 lines):",  # The instruction line
            ]
            
            # Also check if this is part of a multi-line prompt sequence
            is_hypothesis_related = any(pattern in line for pattern in hypothesis_patterns)
            
            # Check if recent lines contained hypothesis prompt indicators
            recent_has_hypothesis = False
            if len(self.detector.recent_lines) > 0:
                for recent in self.detector.recent_lines[-3:]:
                    if any(pattern in recent for pattern in ["Enter hypothesis", "vulnerability hypothesis"]):
                        recent_has_hypothesis = True
                        break
            
            # If this line is related to hypothesis prompt or follows one, hold it
            if (self.detector.is_likely_prompt(line) or 
                is_hypothesis_related or 
                (recent_has_hypothesis and line.startswith("Example:"))):
                # Hold this line - don't send it yet
                self.hold_buffer = self.buffer
                self.buffer = ""
                return
            else:
                # Not a prompt, send any held buffer first
                if self.hold_buffer:
                    await self._send(self.hold_buffer)
                    self.hold_buffer = ""
                
                # Send current buffer
                await self._send(self.buffer)
                self.buffer = ""
                self.last_newline_sent = True
        else:
            # Still building a line
            self.last_newline_sent = False
            
            # If buffer is getting large and we have no held content, send it
            if len(self.buffer) > 200 and not self.hold_buffer:
                await self._send(self.buffer)
                self.buffer = ""
    
    async def flush_if_not_prompt(self):
        """Flush buffers if they don't contain prompts"""
        if self.hold_buffer:
            # We were holding a potential prompt
            line = self.hold_buffer.strip()
            
            # Special check for hypothesis prompts and related lines
            hypothesis_patterns = [
                "Enter hypothesis (press Enter twice when done):",
                "Enter your detailed vulnerability hypothesis",
                "Example: 'This function allows",
                "Example:",
                "(2-3 lines):",
            ]
            
            is_hypothesis_related = any(pattern in line for pattern in hypothesis_patterns)
            
            if not self.detector.is_likely_prompt(line) and not is_hypothesis_related:
                # False alarm, send it
                await self._send(self.hold_buffer)
            self.hold_buffer = ""
        
        if self.buffer:
            line = self.buffer.strip()
            hypothesis_patterns = [
                "Enter hypothesis (press Enter twice when done):",
                "Enter your detailed vulnerability hypothesis",
                "Example: 'This function allows",
                "Example:",
                "(2-3 lines):",
            ]
            
            is_hypothesis_related = any(pattern in line for pattern in hypothesis_patterns)
            
            if not self.detector.is_likely_prompt(line) and not is_hypothesis_related:
                await self._send(self.buffer)
                self.buffer = ""
    
    def clear_prompt(self):
        """Clear held prompt buffer when we confirm it's a prompt"""
        self.hold_buffer = ""
        self.buffer = ""
    
    async def force_flush(self):
        """Force send all buffers"""
        if self.hold_buffer:
            await self._send(self.hold_buffer)
            self.hold_buffer = ""
        if self.buffer:
            await self._send(self.buffer)
            self.buffer = ""
    
    async def _send(self, data: str):
        """Send data via WebSocket"""
        if data and self.ws_manager:
            # Apply sensitive content filtering here
            filtered_data = self._filter_sensitive_content(data)
            if filtered_data:
                await self.ws_manager.send_log(self.run_id, {
                    "type": "output",
                    "data": filtered_data
                })
    
    def _filter_sensitive_content(self, text):
        """Filter out lines containing sensitive information"""
        FILTER_PATTERNS = [
            r'API_KEY:\s*[a-zA-Z0-9\-_]{20,}'
        ]
        
        lines = text.split('\n')
        filtered_lines = []
        
        for line in lines:
            # Check if this line should be filtered
            should_filter = False
            for pattern in FILTER_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    should_filter = True
                    break
            
            if not should_filter:
                filtered_lines.append(line)
        
        # Reconstruct the text, preserving newlines
        result = '\n'.join(filtered_lines)
        
        # Handle edge case where original text ended with newline
        if text.endswith('\n') and not result.endswith('\n'):
            result += '\n'
        
        return result


async def launch_mas_interactive(
    run_id: str, 
    job: dict, 
    input_handler: Callable,
    ws_manager=None,
    log_dir: str = "./backend/logs",
) -> Dict[str, Any]:
    """
    Launch MAS subprocess with interactive input/output support via WebSocket
    
    Args:
        run_id: Unique identifier for this run
        job: Job configuration dictionary
        input_handler: Async function that handles prompts and returns user input
        ws_manager: WebSocket manager for sending logs
        log_dir: Directory for log files
    """
    # Create log directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Create timestamp for log files
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    # Prepare the MAS repository path
    mas_repo = Path(MAS_REPO_PATH).resolve()
    mas_script = mas_repo / "src" / "api" / "agents" / "mas2.py"
    
    print(f"MAS repo path: {mas_repo}")
    print(f"MAS script path: {mas_script}")
    
    if not mas_script.exists():
        error_msg = f"MAS script not found at {mas_script}"
        print(f"ERROR: {error_msg}")
        if ws_manager:
            await ws_manager.send_log(run_id, {
                "type": "error",
                "data": error_msg
            })
        return {"success": False, "error": error_msg}
    
    # Prepare environment variables
    env = os.environ.copy()
    env["PYTHONPATH"] = str(mas_repo / "src")
    
    # Copy over API keys and other environment variables
    optional_env_vars = [
        "OPENAI_API_KEY", "QDRANT_API_KEY", "QDRANT_URL", 
        "ETHERSCAN_API_KEY", "MONGO_URI", "WALLET_PRIVATE_KEY",
        "HUGGINGFACE_API_KEY", "TOGETHER_API_KEY", "REPLICATE_API_TOKEN", 
        "KINDO_API_KEY"
    ]
    
    for var_name in optional_env_vars:
        value = os.getenv(var_name)
        if value is not None:
            env[var_name] = value
    
    cmd = [MAS_PYTHON_PATH, str(mas_script)]
    
    # Log file paths
    log_file_path = log_path / f"{run_id}_{timestamp}_output.log"
    
    try:
        print(f"Starting MAS subprocess...")
        print(f"Command: {' '.join(cmd)}")
        print(f"Working directory: {mas_repo}")
        
        # Send start notification
        if ws_manager:
            await ws_manager.send_log(run_id, {
                "type": "start",
                "data": {
                    "pid": None,
                    "command": ' '.join(cmd),
                    "working_dir": str(mas_repo)
                }
            })

        
        # Create subprocess
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=str(mas_repo)
        )
        
        print(f"Process started with PID: {process.pid}")
        print(f"Logging to: {log_file_path}")
        print("-" * 80)
        
        # Send process started notification
        if ws_manager:
            await ws_manager.send_log(run_id, {
                "type": "process_started",
                "data": {
                    "pid": process.pid,
                    "log_file": str(log_file_path)
                }
            })
        
        # Start a task to monitor stderr
        async def monitor_stderr():
            while True:
                try:
                    stderr_line = await process.stderr.readline()
                    if not stderr_line:
                        break
                    stderr_text = stderr_line.decode('utf-8', errors='ignore')
                    print(f"[STDERR] {stderr_text}", end='')
                    
                    # Log stderr to file
                    with open(log_file_path.with_suffix('.stderr.log'), 'a') as stderr_log:
                        stderr_log.write(stderr_text)
                    
                    # Send stderr via WebSocket
                    if ws_manager:
                        await ws_manager.send_log(run_id, {
                            "type": "stderr",
                            "data": stderr_text
                        })
                except Exception as e:
                    print(f"[STDERR MONITOR ERROR] {e}")
                    break
        
        # Start stderr monitoring in background
        stderr_task = asyncio.create_task(monitor_stderr())
        
        # Initialize prompt detector
        detector = PromptDetector()
        
        # Initialize the smart output buffer
        output_buffer = OutputBuffer(ws_manager, run_id, detector)
        
        # Open log file
        with open(log_file_path, 'w', encoding='utf-8') as log_file:
            buffer = ""
            line_buffer = ""
            all_output = []
            last_char_time = asyncio.get_event_loop().time()
            no_output_count = 0
            
            while True:
                # Read one byte at a time for better control
                try:
                    data = await asyncio.wait_for(process.stdout.read(1), timeout=0.1)
                    no_output_count = 0  # Reset when we get data
                except asyncio.TimeoutError:
                    no_output_count += 1
                    
                    # Flush non-prompt buffers on timeout
                    await output_buffer.flush_if_not_prompt()
                    
                    # No new data - check various conditions
                    current_time = asyncio.get_event_loop().time()
                    time_since_last = current_time - last_char_time
                    
                    # Check if we're in a silent wait state after hypothesis instructions
                    hypothesis_instruction_seen = False
                    for line in detector.recent_lines[-5:]:
                        if "Enter hypothesis (press Enter twice when done):" in line:
                            hypothesis_instruction_seen = True
                            break
                    
                    if hypothesis_instruction_seen and time_since_last > 0.5 and not detector.waiting_for_multiline:
                        # MAS printed hypothesis instructions and is now silently waiting
                        if "hypothesis_silent_wait" in detector.seen_prompts:
                            continue

                        detector.waiting_for_multiline = True
                        detector.seen_prompts.add("hypothesis_silent_wait")
                        
                        # Clear any prompt from output buffer
                        output_buffer.clear_prompt()
                        
                        # Send prompt notification via WebSocket
                        if ws_manager:
                            await ws_manager.send_log(run_id, {
                                "type": "prompt",
                                "data": {
                                    "prompt": '''Enter your detailed vulnerability hypothesis (2-3 lines):\n
                                     Example: 'This function allows reentrancy attacks because it calls external contracts before updating state variables, which could allow attackers to drain funds by repeatedly calling the function.\n'
                                    ''',
                                    "multiline": False  # We handle multiline internally
                                }
                            })
                        
                        # Get the hypothesis input
                        user_input = await input_handler("Enter your detailed vulnerability hypothesis:")
                        
                        if user_input is not None:
                            try:
                                if process.returncode is None:
                                    # Send the entire hypothesis
                                    process.stdin.write((user_input + '\n').encode())
                                    await process.stdin.drain()
                                    
                                    # Send empty line to end input
                                    process.stdin.write('\n'.encode())
                                    await process.stdin.drain()
                                    
                                detector.waiting_for_multiline = False
                                buffer = ""
                                line_buffer = ""
                                
                            except (BrokenPipeError, RuntimeError) as e:
                                print(f"[SHEPHERD] Process terminated while sending input: {e}")
                                if ws_manager:
                                    await ws_manager.send_log(run_id, {
                                        "type": "error",
                                        "data": {
                                            "error": "Process terminated unexpectedly",
                                            "details": str(e)
                                        }
                                    })
                                break
                        
                        no_output_count = 0
                        continue
                    
                    # Special handling for multi-line input mode
                    if detector.waiting_for_multiline and no_output_count > 5:
                        # MAS is silently waiting for more input
                        # Request another line from user via WebSocket
                        if ws_manager:
                            await ws_manager.send_log(run_id, {
                                "type": "prompt_continuation",
                                "data": {
                                    "prompt": "(waiting for more lines...)",
                                    "multiline": True
                                }
                            })
                        
                        # Get input from handler
                        user_input = await input_handler("", multiline_continuation=True)
                        
                        # Send to MAS
                        process.stdin.write((user_input + '\n').encode())
                        await process.stdin.drain()
                        
                        if user_input.strip() == "":
                            detector.multiline_empty_count += 1
                            if detector.multiline_empty_count >= 1:
                                # User pressed enter on empty line, done with multi-line
                                detector.waiting_for_multiline = False
                                detector.multiline_empty_count = 0
                        else:
                            detector.multiline_empty_count = 0
                        
                        no_output_count = 0
                        continue
                    
                    # Normal prompt detection
                    if buffer and detector.should_wait_for_input(buffer, time_since_last):
                        prompt_line = buffer.strip()
                        
                        if "press enter twice" in prompt_line.lower():
                            continue  # handled by silent-wait logic
                        if "detailed vulnerability hypothesis" in prompt_line.lower():
                            continue  # handled by silent-wait logic

                        # Skip if this is the hypothesis case (already handled above)
                        if "hypothesis_silent_wait" in detector.seen_prompts:
                            continue
                        
                        # Skip if already seen this exact prompt
                        if prompt_line in detector.seen_prompts:
                            continue
                        
                        # Clear the prompt from our output buffer
                        output_buffer.clear_prompt()
                        
                        # Mark this prompt as seen
                        detector.seen_prompts.add(prompt_line)
                        
                        # Send prompt notification via WebSocket (this is the ONLY place the prompt should be sent)
                        if ws_manager:
                            await ws_manager.send_log(run_id, {
                                "type": "prompt",
                                "data": {
                                    "prompt": prompt_line,
                                    "multiline": False
                                }
                            })
                        
                        # Get input from handler
                        user_input = await input_handler(prompt_line)
                        
                        if user_input is not None:
                            try:
                                # Normal single line input
                                if process.returncode is None:
                                    process.stdin.write((user_input + '\n').encode())
                                    await process.stdin.drain()
                                
                                buffer = ""
                                line_buffer = ""
                                detector.last_input_time = current_time
                                
                            except (BrokenPipeError, RuntimeError) as e:
                                # Process has terminated
                                print(f"[SHEPHERD] Process terminated while sending input: {e}")
                                if ws_manager:
                                    await ws_manager.send_log(run_id, {
                                        "type": "error",
                                        "data": {
                                            "error": "Process terminated unexpectedly",
                                            "details": str(e)
                                        }
                                    })
                                break
                    
                    # Check if process has ended
                    if process.returncode is not None:
                        break
                    continue
                
                if not data:
                    if process.returncode is not None:
                        break
                    continue
                
                # Update last character time
                last_char_time = asyncio.get_event_loop().time()
                current_time = last_char_time
                
                # Decode character
                char = data.decode('utf-8', errors='ignore')
                buffer += char
                line_buffer += char
                
                # Add to smart output buffer
                await output_buffer.add_char(char)
                
                # Write to log
                log_file.write(char)
                log_file.flush()
                print(char, end='', flush=True)
                all_output.append(char)
                
                # Handle newlines for buffer management
                if char == '\n':
                    # Add completed line to detector history
                    if buffer.strip():
                        detector.add_line(buffer.strip())
                    buffer = ""
                    line_buffer = ""
        
        # Force flush any remaining data
        await output_buffer.force_flush()
        
        # Close stdin
        process.stdin.close()
        
        print(f"\n[SHEPHERD DEBUG] Main loop ended. Process returncode: {process.returncode}")
        print(f"[SHEPHERD DEBUG] Last output lines:")
        for line in detector.recent_lines[-10:]:
            print(f"  > {line}")
            
        # Wait for process to complete
        return_code = await process.wait()
        
        print(f"\n[SHEPHERD] Process exited with code: {return_code}")
        
        last_output = "".join(all_output[-500:]) if all_output else ""
        print(f"[SHEPHERD DEBUG] Last 500 chars of output:\n{last_output}")
        
        # Send completion notification
        if ws_manager:
            await ws_manager.send_log(run_id, {
                "type": "complete",
                "data": {
                    "exit_code": return_code,
                    "success": return_code == 0
                }
            })
        
        return {
            "success": return_code == 0,
            "exit_code": return_code,
            "log_file": str(log_file_path),
            "output": "".join(all_output)
        }
        
    except Exception as e:
        error_msg = f"Failed to launch MAS: {str(e)}"
        print(f"\n[SHEPHERD] ERROR: {error_msg}")
        import traceback
        traceback.print_exc()
        
        # Send error notification
        if ws_manager:
            await ws_manager.send_log(run_id, {
                "type": "error",
                "data": {
                    "error": str(e),
                    "traceback": traceback.format_exc()
                }
            })
        
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }



# Helper function for creating WebSocket-based input handler
def create_ws_input_handler(run_id: str, input_queue: asyncio.Queue):
    """
    Creates an async input handler that waits for input from a WebSocket queue
    """
    async def handler(prompt: str, multiline: bool = False, multiline_continuation: bool = False):
        # Wait for input from the queue
        user_input = await input_queue.get()
        return user_input
    
    return handler