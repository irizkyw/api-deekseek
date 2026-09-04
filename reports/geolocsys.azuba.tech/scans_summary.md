# Scan Summary for geolocsys.azuba.tech

| Timestamp | Tool | Arguments | Log File |
| --- | --- | --- | --- |
| 2026-09-04 15:59:27 | `httpx_probe` | `{"target": "geolocsys.azuba.tech", "additional_args": "-sc -` | [20260904_155927_httpx_probe.json](scans/20260904_155927_httpx_probe.json) |
| 2026-09-04 15:59:33 | `httpx_probe` | `{"target": "geolocsys.azuba.tech", "probe": true, "tech_dete` | [20260904_155933_httpx_probe.json](scans/20260904_155933_httpx_probe.json) |
| 2026-09-04 16:01:45 | `nmap_scan` | `{"target": "geolocsys.azuba.tech", "scan_type": "quick", "ad` | [20260904_160145_nmap_scan.json](scans/20260904_160145_nmap_scan.json) |
| 2026-09-04 16:02:02 | `execute_command` | `{"command": "curl -v -L http://geolocsys.azuba.tech:8001/ 2>` | [20260904_160202_execute_command.json](scans/20260904_160202_execute_command.json) |
| 2026-09-04 16:03:31 | `execute_command` | `{"command": "curl -v http://geolocsys.azuba.tech:8000/ 2>&1 ` | [20260904_160331_execute_command.json](scans/20260904_160331_execute_command.json) |
| 2026-09-04 16:03:47 | `create_vulnerability_report` | `{"vulnerabilities": "[{\"id\":\"RECON-001\",\"name\":\"Open ` | [20260904_160347_create_vulnerability_report.json](scans/20260904_160347_create_vulnerability_report.json) |
| 2026-09-04 16:16:24 | `subfinder_scan` | `{"domain": "geolocsys.azuba.tech", "silent": false, "all_sou` | [20260904_161624_subfinder_scan.json](scans/20260904_161624_subfinder_scan.json) |
| 2026-09-04 16:16:26 | `httpx_probe` | `{"target": "geolocsys.azuba.tech", "probe": true, "tech_dete` | [20260904_161626_httpx_probe.json](scans/20260904_161626_httpx_probe.json) |
| 2026-09-04 16:16:34 | `nmap_scan` | `{"target": "geolocsys.azuba.tech", "scan_type": "quick", "po` | [20260904_161634_nmap_scan.json](scans/20260904_161634_nmap_scan.json) |
| 2026-09-04 16:16:50 | `execute_command` | `{"command": "curl -v http://geolocsys.azuba.tech:8000/", "us` | [20260904_161650_execute_command.json](scans/20260904_161650_execute_command.json) |
| 2026-09-04 16:17:08 | `execute_command` | `{"command": "ls /usr/share/wordlists/dirbuster/", "use_cache` | [20260904_161708_execute_command.json](scans/20260904_161708_execute_command.json) |
| 2026-09-04 16:17:24 | `execute_command` | `{"command": "ls /usr/share/wordlists/", "use_cache": false}` | [20260904_161724_execute_command.json](scans/20260904_161724_execute_command.json) |
| 2026-09-04 16:17:36 | `execute_command` | `{"command": "echo -e \"admin\napi\ndashboard\nlogin\nregiste` | [20260904_161736_execute_command.json](scans/20260904_161736_execute_command.json) |
| 2026-09-04 16:17:49 | `execute_command` | `{"command": "curl -v http://geolocsys.azuba.tech:8000/admin ` | [20260904_161749_execute_command.json](scans/20260904_161749_execute_command.json) |
| 2026-09-04 16:17:57 | `execute_command` | `{"command": "find /usr -name \"*.txt\" -path \"*/wordlists/*` | [20260904_161757_execute_command.json](scans/20260904_161757_execute_command.json) |
| 2026-09-04 16:18:12 | `execute_command` | `{"command": "find /usr/share -name \"common.txt\" 2>/dev/nul` | [20260904_161812_execute_command.json](scans/20260904_161812_execute_command.json) |
| 2026-09-04 16:20:26 | `mcp__exnomous-helper__save_deliverable` | `{"deliverable_type": "RECON", "content": "# Reconnaissance D` | [20260904_162026_mcp__exnomous-helper__save_deliverable.txt](scans/20260904_162026_mcp__exnomous-helper__save_deliverable.txt) |
| 2026-09-04 16:20:59 | `write_file` | `{"path": "deliverables/recon_deliverable.md", "content": "# ` | [20260904_162059_write_file.txt](scans/20260904_162059_write_file.txt) |
| 2026-09-04 16:21:01 | `list_directory` | `{"path": "."}` | [20260904_162101_list_directory.txt](scans/20260904_162101_list_directory.txt) |
| 2026-09-04 16:21:34 | `write_file` | `{"path": "recon_deliverable.md", "content": "# Reconnaissanc` | [20260904_162134_write_file.txt](scans/20260904_162134_write_file.txt) |
| 2026-09-04 16:26:50 | `execute_command` | `{"command": "curl -v -c /tmp/cookies.txt http://geolocsys.az` | [20260904_162650_execute_command.json](scans/20260904_162650_execute_command.json) |
| 2026-09-04 16:27:25 | `write_file` | `{"path": "geolocsys_azuba_tech_executive_report.md", "conten` | [20260904_162725_write_file.txt](scans/20260904_162725_write_file.txt) |
| 2026-09-04 16:43:49 | `gau_discovery` | `{"domain": "geolocsys.azuba.tech", "include_subs": true}` | [20260904_164349_gau_discovery.json](scans/20260904_164349_gau_discovery.json) |
| 2026-09-04 16:44:55 | `write_file` | `{"path": "recon_deliverable.md", "content": "# Reconnaissanc` | [20260904_164455_write_file.txt](scans/20260904_164455_write_file.txt) |
| 2026-09-04 17:23:23 | `subfinder_scan` | `{"domain": "geolocsys.azuba.tech", "silent": false, "all_sou` | [20260904_172323_subfinder_scan.json](scans/20260904_172323_subfinder_scan.json) |
| 2026-09-04 17:23:27 | `httpx_probe` | `{"target": "https://geolocsys.azuba.tech", "probe": true, "t` | [20260904_172327_httpx_probe.json](scans/20260904_172327_httpx_probe.json) |
| 2026-09-04 17:23:31 | `httpx_probe` | `{"target": "geolocsys.azuba.tech", "probe": true, "tech_dete` | [20260904_172331_httpx_probe.json](scans/20260904_172331_httpx_probe.json) |
| 2026-09-04 17:23:37 | `nmap_scan` | `{"target": "geolocsys.azuba.tech", "scan_type": "quick", "po` | [20260904_172337_nmap_scan.json](scans/20260904_172337_nmap_scan.json) |
| 2026-09-04 17:23:40 | `dirsearch_scan` | `{"url": "https://geolocsys.azuba.tech", "extensions": "php,h` | [20260904_172340_dirsearch_scan.json](scans/20260904_172340_dirsearch_scan.json) |
| 2026-09-04 17:23:44 | `http_framework_test` | `{"url": "https://geolocsys.azuba.tech", "method": "GET", "ac` | [20260904_172344_http_framework_test.json](scans/20260904_172344_http_framework_test.json) |
| 2026-09-04 17:23:49 | `execute_command` | `{"command": "curl -k -I https://geolocsys.azuba.tech", "use_` | [20260904_172349_execute_command.json](scans/20260904_172349_execute_command.json) |
| 2026-09-04 17:23:52 | `gobuster_scan` | `{"url": "https://geolocsys.azuba.tech", "mode": "dir", "word` | [20260904_172352_gobuster_scan.json](scans/20260904_172352_gobuster_scan.json) |
| 2026-09-04 17:23:55 | `feroxbuster_scan` | `{"url": "https://geolocsys.azuba.tech", "wordlist": "/usr/sh` | [20260904_172355_feroxbuster_scan.json](scans/20260904_172355_feroxbuster_scan.json) |
| 2026-09-04 17:24:28 | `execute_command` | `{"command": "curl -k -L https://geolocsys.azuba.tech/login/ ` | [20260904_172428_execute_command.json](scans/20260904_172428_execute_command.json) |
| 2026-09-04 17:24:37 | `execute_command` | `{"command": "curl -k -X POST https://geolocsys.azuba.tech/ap` | [20260904_172437_execute_command.json](scans/20260904_172437_execute_command.json) |
| 2026-09-04 17:24:44 | `execute_command` | `{"command": "which ffuf \|\| echo \"ffuf not found\"", "use_ca` | [20260904_172444_execute_command.json](scans/20260904_172444_execute_command.json) |
| 2026-09-04 17:24:49 | `execute_command` | `{"command": "find /usr/share/wordlists -name \"common.txt\" ` | [20260904_172449_execute_command.json](scans/20260904_172449_execute_command.json) |
| 2026-09-04 17:25:08 | `execute_command` | `{"command": "curl -k -s -o /dev/null -w \"%{http_code}\" htt` | [20260904_172508_execute_command.json](scans/20260904_172508_execute_command.json) |
| 2026-09-04 17:26:21 | `nuclei_scan` | `{"target": "https://geolocsys.azuba.tech", "severity": "low,` | [20260904_172621_nuclei_scan.json](scans/20260904_172621_nuclei_scan.json) |
| 2026-09-04 17:26:38 | `write_file` | `{"path": "assessment_report_geolocsys.md", "content": "# Sec` | [20260904_172638_write_file.txt](scans/20260904_172638_write_file.txt) |
