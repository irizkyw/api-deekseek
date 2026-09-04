import os
import sys
import json
import asyncio
import threading
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

class MCPManager:
    """
    Manages connections to stdio MCP servers configured in Claude Desktop config.
    Runs an internal asyncio event loop in a background thread to handle stdio communication.
    """
    def __init__(self, config_path: str = None):
        if not config_path:
            candidates = [
                os.getenv("MCP_CONFIG_PATH", ""),
                os.path.join(os.getcwd(), "mcp_config.json"),
                os.path.expanduser("~/.config/Claude/claude_desktop_config.json"),
                os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json"),
                os.path.expanduser("~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"),
                os.path.expanduser("~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json"),
            ]
            appdata = os.getenv("APPDATA", "")
            if appdata:
                candidates.append(os.path.join(appdata, "Claude", "claude_desktop_config.json"))

            config_path = ""
            for candidate in candidates:
                if candidate and os.path.exists(candidate):
                    config_path = candidate
                    break
                
        self.config_path = config_path
        self.sessions: Dict[str, ClientSession] = {}
        self.transports = []  # keep references to prevent garbage collection
        self.errlog_files: List[Any] = []
        self.tools: Dict[str, Tuple[str, Any]] = {}  # {tool_name: (server_name, tool_obj)}
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coro(self, coro):
        """Helper to run a coroutine in the background thread's event loop and wait for result."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    def load_servers(self) -> List[str]:
        """Loads and initializes configured stdio MCP servers. Returns list of active server names."""
        if not self.config_path or not os.path.exists(self.config_path):
            return []

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            return []

        mcp_servers = config.get("mcpServers", {})
        active_servers = []

        for name, cfg in mcp_servers.items():
            # Skip ourselves to avoid infinite loops/self-calling
            if "deepseek-free" in name:
                continue

            command = cfg.get("command")
            if command in ("python", "python3") and sys.executable:
                command = sys.executable

            args = []
            for arg in cfg.get("args", []):
                if isinstance(arg, str) and (arg.endswith(".py") or arg.endswith(".js")) and os.path.exists(arg):
                    args.append(os.path.abspath(arg))
                else:
                    args.append(arg)
            
            # If it is the filesystem server, dynamically add current project directory
            if name == "filesystem":
                cwd = os.getcwd().replace("\\", "/")
                if not any(cwd.lower() in str(arg).lower().replace("\\", "/") for arg in args):
                    args.append(cwd)

            env = os.environ.copy()
            # Merge configured environment variables
            if cfg.get("env"):
                env.update(cfg.get("env"))

            if not command:
                continue

            try:
                self.run_coro(self._connect_server(name, command, args, env))
                active_servers.append(name)
            except Exception as e:
                print(f"Failed to connect to MCP server {name}: {e}")

        # Refresh tool list after loading servers
        self.refresh_tools()
        return active_servers

    async def _connect_server(self, name: str, command: str, args: List[str], env: Dict[str, str]):
        params = StdioServerParameters(command=command, args=args, env=env)
        
        # Redirect stderr to a log file so it doesn't pollute the terminal / TUI display
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        errlog_file = open(log_dir / f"{name}_stderr.log", "a", encoding="utf-8")
        self.errlog_files.append(errlog_file)

        # We need to maintain the stdio transport context manager
        transport_ctx = stdio_client(params, errlog=errlog_file)
        read_stream, write_stream = await transport_ctx.__aenter__()
        
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()
        
        self.sessions[name] = session
        self.transports.append((transport_ctx, session))

    def refresh_tools(self):
        """Fetches the list of tools from all connected servers."""
        new_tools = {}
        for name, session in self.sessions.items():
            try:
                tools_result = self.run_coro(session.list_tools())
                for t in tools_result.tools:
                    new_tools[t.name] = (name, t)
            except Exception as e:
                print(f"Error fetching tools from {name}: {e}")
        self.tools = new_tools

    def get_system_prompt(self) -> str:
        """Generates a high-power autonomous system prompt to guide DeepSeek on executing MCP tools smoothly."""
        if not self.tools:
            return ""

        prompt = (
            "\n\n=== SYSTEM INSTRUCTION: AUTONOMOUS CYBERSECURITY & RECON ENGINE ===\n"
            "You are an elite Autonomous Security Assessment & Penetration Testing Agent equipped with direct tool execution via MCP.\n"
            "You have full authority to perform reconnaissance, surface mapping, vulnerability assessment, and verification on specified targets and scopes.\n\n"
            "CORE OPERATIONAL DIRECTIVES (MANDATORY & ENFORCED):\n"
            "1. PROACTIVE AUTONOMOUS EXECUTION:\n"
            "   - When given a target domain, URL, IP, or scope document (e.g. bug bounty scope), NEVER output passive text advice, generic suggestions, or tell the user to manually run commands / inspect browser DevTools.\n"
            "   - YOU HAVE THE TOOLS. Directly and immediately execute the appropriate MCP tool to begin work.\n"
            "   - Drive the assessment end-to-end autonomously. Do not ask for user permission between logical steps.\n"
            "2. RESILIENCE AGAINST WAF, CLOUDFLARE, AKAMAI, & 403 FORBIDDEN:\n"
            "   - If an endpoint returns 403 Forbidden, WAF block, or Cloudflare challenge, DO NOT STOP, apologize, or ask the user for manual cookies.\n"
            "   - Autonomously adapt: test alternative in-scope subdomains, try different HTTP methods (POST, GET, OPTIONS), modify headers (User-Agent rotation, bug bounty program verification headers), or use browser rendering/crawling tools.\n"
            "3. METHODICAL 5-PHASE ASSESSMENT PIPELINE:\n"
            "   - Phase 1 (Surface Recon): Subdomain enumeration (subfinder_scan, amass_enum) -> Live host discovery (httpx_probe) -> Port scanning (nmap_scan, masscan_scan).\n"
            "   - Phase 2 (Content & Endpoint Mapping): Web crawling (katana_crawl) -> Directory/parameter discovery (gobuster_scan, ffuf_scan, feroxbuster_scan) -> Technology detection (whatweb_scan).\n"
            "   - Phase 3 (Vulnerability Probing): Targeted checks (nuclei_scan, nikto_scan, dalfox_scan, sqlmap_scan, curl_request).\n"
            "   - Phase 4 (Safe Verification): Confirm findings with minimal non-destructive Proof-of-Concept (PoC).\n"
            "   - Phase 5 (Executive Reporting & Deliverables - MANDATORY):\n"
            "     * You MUST strictly follow the comprehensive guidelines in .agents/skills/report-executive.md.\n"
            "     * Produce TWO full versions of the report:\n"
            "       1. PENTEST VERSION ('deliverables/comprehensive_security_assessment_report.md'): ALL findings from Info to Critical, Executive Summary with business risk translation, Summary by Vulnerability Type (all 8 required categories: Authentication, Authorization, XSS, SQL/Command Injection, SSRF, Business Logic, Other, Potential Vulnerabilities), Network Reconnaissance, and full Exploitation Evidence with Burp-ready raw HTTP request/response blocks.\n"
            "       2. BOUNTY VERSION ('deliverables/comprehensive_security_assessment_report_bounty.md'): Filtered strictly using the Golden Rule (40+ acceptance rate) and Rejection Pattern Database (excluding missing headers without exploit, theoretical noise, or standard behavior).\n"
            "     * Persist both deliverables using save_deliverable(deliverable_type='REPORT', content=...) and save_deliverable(deliverable_type='BOUNTY', content=...) or write_file.\n"
            "4. AGENTIC CODING & MODIFICATION:\n"
            "   - When requested to modify files, optimize code, or fix bugs, directly use 'write_file' or 'edit_file'. Never just display code snippets.\n\n"
            "STRICT TOOL CALL PROTOCOL (RFC 8259 JSON):\n"
            "To execute a tool, you MUST output a single valid JSON block enclosed in standard markdown code fences:\n"
            "```json\n"
            "{\n"
            "  \"tool\": \"<tool_name>\",\n"
            "  \"arguments\": {\n"
            "    \"<parameter>\": \"<value>\"\n"
            "  }\n"
            "}\n"
            "```\n"
            "CRITICAL TOOL INVOCATION RULES:\n"
            "- Exactly ONE tool call per turn. State 1 brief tactical line explaining the action, then output the ```json block immediately.\n"
            "- Do NOT generate text after the ```json ``` block. Stop and wait for the tool output in the subsequent turn.\n"
            "- Strict JSON validity: double quotes for all keys and strings, NO trailing commas, NO comments (no // or /* */) inside the JSON block.\n\n"
            "AVAILABLE MCP TOOLS REGISTRY:\n"
        )

        for name, (server, t) in self.tools.items():
            desc = (t.description or "").strip()
            # Extract summary before Args/Returns
            desc_summary = desc.split("Args:")[0].split("Returns:")[0].strip()
            desc_summary = re.sub(r"\s+", " ", desc_summary)
            if len(desc_summary) > 160:
                desc_summary = desc_summary[:157] + "..."

            schema = getattr(t, "inputSchema", {})
            properties = schema.get("properties", {})
            required = set(schema.get("required", []))

            param_strs = []
            for p_name, p_cfg in properties.items():
                req_star = "*" if p_name in required else ""
                p_type = p_cfg.get("type", "any")
                param_strs.append(f"{p_name}{req_star} ({p_type})")

            params_line = ", ".join(param_strs) if param_strs else "none"
            prompt += f"- Tool: {name} [{server}]: {desc_summary}\n  Parameters: {params_line}\n"

        prompt += (
            "\n==================================================\n"
            "OPERATIONAL DIRECTIVES:\n"
            "- THOROUGH & COMPREHENSIVE: Be completely thorough across all phases. Do NOT skip or omit any discovered endpoints, open ports, technologies, parameters, or potential vulnerabilities.\n"
            "- REPORT-EXECUTIVE MANDATE: You MUST execute all skills in .agents/skills/report-executive.md without truncation, generating both Pentest and Bounty versions.\n"
            "- EFFICIENT SCANNING: For directory/endpoint fuzzing, use scanning tools with wordlist files such as /usr/share/dirb/wordlists/common.txt rather than constructing giant inline wordlists via bash echo commands.\n"
            "- FULL DETAIL DELIVERABLES: Ensure every deliverable includes complete technical analysis, proof of concept, and actionable remediation without omitting any important information.\n"
            "READY: Evaluate the objective and execute your first tool call now!\n"
            "==================================================\n"
        )
        return prompt

    def get_tool_reminder_prompt(self) -> str:
        """Concise reminder for multi-turn tool loops so DeepSeek keeps invoking tools autonomously."""
        if not self.tools:
            return ""
        return (
            "\n\n[AUTONOMOUS DIRECTIVE: Tool telemetry received above.\n"
            "1. Thoroughly analyze ALL findings (open ports, discovered endpoints, HTTP status, headers, technologies, anomalies).\n"
            "2. If next phase is required, IMMEDIATELY call the next tool via ```json {\"tool\": \"...\", \"arguments\": {...}} ```.\n"
            "3. If blocked or failed, pivot autonomously to alternative endpoints, parameters, or tools.\n"
            "4. For directory/file discovery, leverage wordlist files (e.g. /usr/share/dirb/wordlists/common.txt) with scanning tools.\n"
            "5. Do NOT omit or cut any important findings; provide a complete, detailed assessment report when testing is finished.]\n"
        )

    def _handle_helper_tool(self, clean_name: str, arguments: Dict[str, Any], target: str = "") -> str:
        """Handles helper/virtual tools expected by security skills (e.g. deliverable persistence, session helpers)."""
        if clean_name == "save_deliverable":
            deliverable_type = str(arguments.get("deliverable_type", "REPORT")).upper()
            content = str(arguments.get("content", ""))

            # Standard type map according to .agents/skills/ specifications
            type_file_map = {
                # 1. pre-recon-browser.md
                "BROWSER_ANALYSIS": "browser_analysis_deliverable.md",
                "PRE_RECON": "pre_recon_deliverable.md",
                "CODE_ANALYSIS": "code_analysis_deliverable.md",

                # 2. recon.md
                "RECON": "recon_deliverable.md",

                # 3. vuln-all.md
                "ALL_ANALYSIS": "all_analysis_deliverable.md",
                "ALL_QUEUE": "all_exploitation_queue.json",
                "OTHER_ANALYSIS": "other_analysis_deliverable.md",
                "OTHER_QUEUE": "other_exploitation_queue.json",
                "ANALYSIS": "other_analysis_deliverable.md",
                "QUEUE": "other_exploitation_queue.json",

                # 4. exploit-all.md
                "OTHER_EVIDENCE": "other_exploitation_evidence.md",
                "ALL_EVIDENCE": "all_exploitation_evidence.md",
                "EVIDENCE": "other_exploitation_evidence.md",
                "EXPLOIT": "other_exploitation_evidence.md",
                "AUTH_EVIDENCE": "auth_exploitation_evidence.md",
                "AUTHZ_EVIDENCE": "authz_exploitation_evidence.md",
                "INJECTION_EVIDENCE": "injection_exploitation_evidence.md",
                "XSS_EVIDENCE": "xss_exploitation_evidence.md",
                "SSRF_EVIDENCE": "ssrf_exploitation_evidence.md",
                "LOGIC_EVIDENCE": "logic_exploitation_evidence.md",
                "SECRETS_EVIDENCE": "secrets_exploitation_evidence.md",
                "CORS_EVIDENCE": "cors_exploitation_evidence.md",
                "CACHE_EVIDENCE": "cache_exploitation_evidence.md",
                "UPLOAD_EVIDENCE": "upload_exploitation_evidence.md",
                "SMUGGLING_EVIDENCE": "smuggling_exploitation_evidence.md",

                # 5. report-executive.md
                "REPORT": "comprehensive_security_assessment_report.md",
                "EXECUTIVE": "comprehensive_security_assessment_report.md",
                "EXECUTIVE_REPORT": "comprehensive_security_assessment_report.md",
                "PENTEST": "comprehensive_security_assessment_report.md",
                "PENTEST_REPORT": "comprehensive_security_assessment_report.md",
                "BOUNTY": "comprehensive_security_assessment_report_bounty.md",
                "BOUNTY_REPORT": "comprehensive_security_assessment_report_bounty.md",
            }
            filename = type_file_map.get(deliverable_type, f"{deliverable_type.lower()}_deliverable.md")

            # Detect target if not passed
            if not target:
                target_match = re.search(r"(?:Target|Deliverable|Scope)[:\s]+([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", content)
                if target_match:
                    target = target_match.group(1)
                else:
                    target = "assessment"

            saved_paths = []
            # 1. Save to reports/<target>/<filename>
            rep_dir = os.path.join(os.getcwd(), "reports", target)
            os.makedirs(rep_dir, exist_ok=True)
            rep_path = os.path.join(rep_dir, filename)
            try:
                with open(rep_path, "w", encoding="utf-8") as f:
                    f.write(content)
                saved_paths.append(rep_path)
            except Exception:
                pass

            # 2. Save to /home/xcfa/Projects/deliverables/<filename> (for MCP filesystem root access)
            proj_deliv = "/home/xcfa/Projects/deliverables"
            try:
                os.makedirs(proj_deliv, exist_ok=True)
                p_path = os.path.join(proj_deliv, filename)
                with open(p_path, "w", encoding="utf-8") as f:
                    f.write(content)
                saved_paths.append(p_path)
            except Exception:
                pass

            # 3. Save to workspace deliverables/<filename>
            local_deliv = os.path.join(os.getcwd(), "deliverables")
            try:
                os.makedirs(local_deliv, exist_ok=True)
                l_path = os.path.join(local_deliv, filename)
                with open(l_path, "w", encoding="utf-8") as f:
                    f.write(content)
                saved_paths.append(l_path)
            except Exception:
                pass

            # Also create friendly generic aliases if specific category was saved
            if deliverable_type in ("OTHER_ANALYSIS", "ALL_ANALYSIS"):
                for d in (proj_deliv, local_deliv, rep_dir):
                    try:
                        with open(os.path.join(d, "analysis_deliverable.md"), "w", encoding="utf-8") as f:
                            f.write(content)
                    except Exception:
                        pass
            elif deliverable_type in ("OTHER_QUEUE", "ALL_QUEUE"):
                for d in (proj_deliv, local_deliv, rep_dir):
                    try:
                        with open(os.path.join(d, "exploitation_queue.json"), "w", encoding="utf-8") as f:
                            f.write(content)
                    except Exception:
                        pass
            elif deliverable_type in ("OTHER_EVIDENCE", "ALL_EVIDENCE"):
                for d in (proj_deliv, local_deliv, rep_dir):
                    try:
                        with open(os.path.join(d, "exploitation_evidence.md"), "w", encoding="utf-8") as f:
                            f.write(content)
                    except Exception:
                        pass

            return json.dumps({
                "status": "success",
                "deliverable_type": deliverable_type,
                "filepath": f"deliverables/{filename}",
                "saved_to": saved_paths,
                "message": f"Successfully persisted {deliverable_type} deliverable to deliverables/{filename}"
            })

        elif clean_name in ("get_session", "get_credentials"):
            return json.dumps({
                "status": "none",
                "session": None,
                "credentials": [],
                "message": "No pre-existing credentials/sessions configured. Proceed with unauthenticated reconnaissance and attack surface mapping."
            })

        elif clean_name == "coordinate_login":
            return json.dumps({
                "status": "success",
                "lock_acquired": True,
                "message": "Login coordinator initialized. You may proceed."
            })

        elif clean_name in ("save_session", "save_credentials", "save_verification_code"):
            return json.dumps({
                "status": "success",
                "message": f"{clean_name} data saved successfully."
            })

        elif clean_name in ("read_temp_mail", "get_verification_code"):
            return json.dumps({
                "status": "empty",
                "emails": [],
                "code": None,
                "message": "Inbox is empty."
            })

        return json.dumps({
            "status": "success",
            "message": f"Helper tool '{clean_name}' acknowledged."
        })

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], target: str = "") -> str:
        """Executes a tool on the target MCP server with schema-aware parameter normalization."""
        # Handle virtual helper tools from security skills
        if tool_name.startswith("mcp__exnomous-helper__") or tool_name in (
            "save_deliverable", "get_session", "coordinate_login", "save_session",
            "get_credentials", "save_credentials", "read_temp_mail",
            "save_verification_code", "get_verification_code"
        ):
            clean_name = tool_name.replace("mcp__exnomous-helper__", "")
            return self._handle_helper_tool(clean_name, arguments, target=target)

        # Ensure parent directory exists for write_file
        if tool_name == "write_file" and isinstance(arguments, dict):
            fpath = arguments.get("path") or arguments.get("file_path")
            if fpath:
                full_p = os.path.join("/home/xcfa/Projects", fpath) if not os.path.isabs(fpath) else fpath
                try:
                    os.makedirs(os.path.dirname(full_p), exist_ok=True)
                except Exception:
                    pass

        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' is not registered."

        server_name, tool_obj = self.tools[tool_name]

        # Schema-aware argument auto-normalization
        if isinstance(arguments, dict):
            schema = getattr(tool_obj, "inputSchema", {})
            properties = schema.get("properties", {})

            # Map target / url / domain / host / target_url aliases
            if "target" in properties and "target" not in arguments:
                for alias in ("url", "domain", "host", "target_url", "ip"):
                    if alias in arguments:
                        arguments["target"] = arguments[alias]
                        break
            if "url" in properties and "url" not in arguments:
                for alias in ("target", "target_url", "domain", "host"):
                    if alias in arguments:
                        arguments["url"] = arguments[alias]
                        break
            if "domain" in properties and "domain" not in arguments:
                for alias in ("target", "url", "host"):
                    if alias in arguments:
                        val = str(arguments[alias])
                        val = re.sub(r"^https?://", "", val).split("/")[0].split(":")[0]
                        arguments["domain"] = val
                        break
            if "target_url" in properties and "target_url" not in arguments:
                for alias in ("url", "target"):
                    if alias in arguments:
                        arguments["target_url"] = arguments[alias]
                        break
            if "path" in properties and "path" not in arguments:
                for alias in ("file_path", "filepath", "filename"):
                    if alias in arguments:
                        arguments["path"] = arguments[alias]
                        break
            if "file_path" in properties and "file_path" not in arguments:
                for alias in ("path", "filepath", "filename"):
                    if alias in arguments:
                        arguments["file_path"] = arguments[alias]
                        break

            # Auto-correct common LLM argument naming mistakes for edit_file
            if tool_name == "edit_file":
                edits = arguments.get("edits", [])
                if isinstance(edits, list):
                    for item in edits:
                        if isinstance(item, dict):
                            # Map old/old_text -> oldText
                            if "old" in item and "oldText" not in item:
                                item["oldText"] = item.pop("old")
                            if "old_text" in item and "oldText" not in item:
                                item["oldText"] = item.pop("old_text")
                            
                            # Map new/new_text -> newText
                            if "new" in item and "newText" not in item:
                                item["newText"] = item.pop("new")
                            if "new_text" in item and "newText" not in item:
                                item["newText"] = item.pop("new_text")

                            # Ensure both are strings and present to avoid Zod schema validation errors
                            if "oldText" not in item or item["oldText"] is None:
                                item["oldText"] = ""
                            if "newText" not in item or item["newText"] is None:
                                item["newText"] = ""

        session = self.sessions.get(server_name)
        if not session:
            return f"Error: Session for server '{server_name}' is lost."

        try:
            result = self.run_coro(session.call_tool(tool_name, arguments))
            
            # Format text contents of the response
            output_parts = []
            for content in result.content:
                if content.type == "text":
                    output_parts.append(content.text)
                elif content.type == "image":
                    output_parts.append(f"[Image content generated: {content.mimeType}]")
            res_text = "\n".join(output_parts)
            
            # Auto-mirror written reports and deliverables to local reports/<target>/ and deliverables/
            if tool_name == "write_file" and isinstance(arguments, dict):
                fpath = arguments.get("path") or arguments.get("file_path") or ""
                content_str = str(arguments.get("content", ""))
                fname = os.path.basename(fpath)
                if fname and content_str:
                    tgt = target or "geolocsys.azuba.tech"
                    rep_dir = os.path.join(os.getcwd(), "reports", tgt)
                    deliv_dir = os.path.join(os.getcwd(), "deliverables")
                    try:
                        os.makedirs(rep_dir, exist_ok=True)
                        os.makedirs(deliv_dir, exist_ok=True)
                        if any(k in fname.lower() for k in ("report", "deliverable", "evidence", "queue", "analysis")):
                            with open(os.path.join(rep_dir, fname), "w", encoding="utf-8") as f:
                                f.write(content_str)
                            with open(os.path.join(deliv_dir, fname), "w", encoding="utf-8") as f:
                                f.write(content_str)
                    except Exception:
                        pass

            return res_text
        except Exception as e:
            return f"Error executing tool '{tool_name}': {e}"

    def close(self):
        """Closes all connected MCP server sessions."""
        for _, session in self.transports:
            try:
                self.run_coro(session.__aexit__(None, None, None))
            except Exception:
                pass
        for ctx, _ in self.transports:
            try:
                self.run_coro(ctx.__aexit__(None, None, None))
            except Exception:
                pass
        for f in self.errlog_files:
            try:
                f.close()
            except Exception:
                pass
        self.errlog_files.clear()
        self.loop.call_soon_threadsafe(self.loop.stop)
