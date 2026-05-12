import time
import socket
from enum import Enum

class LLMProvider(Enum):
    OLLAMA_LOCAL = 1
    OPEN_ROUTER = 2
    CHAT_GPT = 3
    VLLM = 4
    GEMINI = 5
    GROK = 6
    CLAUDE = 7
    CHUTES = 8
    CEREBRAS = 9
    GROQ = 10
    NVIDIA = 11
    PERPLEXITY = 12

    @staticmethod
    def from_str(value: str) -> 'LLMProvider':
         match value.upper():
            case "OLLAMA_LOCAL":
                return LLMProvider.OLLAMA_LOCAL
            case "OPEN_ROUTER":
                return LLMProvider.OPEN_ROUTER
            case "CHAT_GPT":
                return LLMProvider.CHAT_GPT
            case "VLLM":
                return LLMProvider.VLLM
            case "GEMINI":
                return LLMProvider.GEMINI
            case "GROK":
                return LLMProvider.GROK
            case "CLAUDE":
                return LLMProvider.CLAUDE
            case "CHUTES":
                return LLMProvider.CHUTES
            case "CEREBRAS":
                return LLMProvider.CEREBRAS
            case "GROQ":
                return LLMProvider.GROQ
            case "NVIDIA":
                return LLMProvider.NVIDIA
            case "PERPLEXITY":
                return LLMProvider.PERPLEXITY        
            case _:
                raise ValueError("Unknown LLMPRovider server")
        
    def __str__(self):
        return self.name.upper()


class LLMProviderStats:
    @staticmethod
    def tcp_ping(ip_address: str, port: int = 80, timeout: float = 10) -> tuple[bool, str]:
        """Perform a TCP-based ping by connecting to the IP/port and measuring time."""
        try:
            start_time = time.time()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((ip_address, port))
                end_time = time.time()
                if result == 0:
                    latency = (end_time - start_time) * 1000  # ms
                    return True, f"{latency}"
                else:
                    return False, ""
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def provider_domain(provider: LLMProvider) -> str:
        match provider:
            case LLMProvider.OLLAMA_LOCAL:
                return ""
            case LLMProvider.CHAT_GPT:
                return "api.openai.com"
            case LLMProvider.OPEN_ROUTER:
                return "openrouter.ai"
            case LLMProvider.VLLM:
                return ""
            case LLMProvider.GEMINI:
                return "generativelanguage.googleapis.com"
            case LLMProvider.GROK:
                return "api.x.ai"
            case LLMProvider.CLAUDE:
                return "api.anthropic.com"
            case LLMProvider.CHUTES:
                return "llm.chutes.ai"
            case LLMProvider.CEREBRAS:
                return "api.cerebras.ai"
            case LLMProvider.GROQ:
                return "api.groq.com"
            case LLMProvider.NVIDIA:
                return "integrate.api.nvidia.com"
            case LLMProvider.PERPLEXITY:
                return "api.perplexity.ai"
            case _:
                raise ValueError("Unknown LLMProvider server")  
            
    @staticmethod
    def provider_port(provider: LLMProvider) -> int:
        match provider:
            case LLMProvider.OLLAMA_LOCAL:
                return 80  # Assuming local HTTP
            case LLMProvider.CHAT_GPT:
                return 443  # HTTPS
            case LLMProvider.OPEN_ROUTER:
                return 443
            case LLMProvider.VLLM:
                return 80
            case LLMProvider.GEMINI:
                return 443
            case LLMProvider.GROK:
                return 443
            case LLMProvider.CLAUDE:
                return 443
            case LLMProvider.CHUTES:
                return 443
            case LLMProvider.CEREBRAS:
                return 443
            case LLMProvider.GROQ:
                return 443
            case LLMProvider.NVIDIA:
                return 443
            case LLMProvider.PERPLEXITY:
                return 443
            case _:
                return 80  # Default fallback

    @staticmethod
    def ping_provider(provider: LLMProvider) -> str:
        domain = LLMProviderStats.provider_domain(provider)
        if not domain:
            return f"No domain to ping for provider {provider} (likely local)."
        
        try:
            ip_address = socket.gethostbyname(domain)
        except socket.gaierror:
            ip_address = "DNS resolution failed"
        
        port = LLMProviderStats.provider_port(provider)        
        print(f"Pinging provider {provider} at domain {domain} (IP: {ip_address}, Port: {port})")
        
        avg_ping_time = "N/A"
        ping_status = "Failure"
        try:
            ping_result, latency = LLMProviderStats.tcp_ping(ip_address, port=port)
            if ping_result:
                ping_status = "Success"
                f = float(latency)
                avg_ping_time = f"{f:.2f} ms"
            else:
                ping_status = "Failure (No response)"
        except Exception as e:
            ping_status = f"Failure ({str(e)})"       
        
        
        table_data = [
            ("Provider", str(provider)),
            ("Domain", domain),
            ("IP Address", ip_address),
            ("Ping Status", ping_status),
            ("Average Ping Time", avg_ping_time),
            # ("Traceroute Results", trace_output)
        ]        
        
        col_width_metric = 20
        col_width_details = 80
        
        output = ""
        output += "+" + "-" * col_width_metric + "+" + "-" * col_width_details + "+\n"
        output += f"| {'Metric'.ljust(col_width_metric)} | {'Details'.ljust(col_width_details)} |\n"
        output += "+" + "-" * col_width_metric + "+" + "-" * col_width_details + "+\n"
        
        for metric, details in table_data:
            details = details[:col_width_details-3] + "..." if len(details) > col_width_details else details
            output += f"| {metric.ljust(col_width_metric)} | {details.ljust(col_width_details)} |\n"
        
        output += "+" + "-" * col_width_metric + "+" + "-" * col_width_details + "+\n"
        
        return output
    
    @staticmethod
    def ping_provider_html(provider: LLMProvider) -> str:
        """Returns an HTML snippet (table) for the given LLMProvider's ping report."""
        domain = LLMProviderStats.provider_domain(provider)
        if not domain:
            return f"<p>No domain to ping for provider {provider} (likely local).</p>"            
        
        try:
            ip_address = socket.gethostbyname(domain)
        except socket.gaierror:
            ip_address = "DNS resolution failed"
    
        port = LLMProviderStats.provider_port(provider)    
        print(f"Pinging provider {provider} at domain {domain} (IP: {ip_address}, Port: {port})")
                
        avg_ping_time = "N/A"
        ping_status = "Failure"
        try:            
            ping_result, latency = LLMProviderStats.tcp_ping(ip_address, port=port)
            if ping_result:
                ping_status = "Success"  
                f = float(latency)              
                avg_ping_time = f"{f:.2f} ms"
            else:
                ping_status = "Failure (No response)"        
        except Exception as e:
            ping_status = f"Failure ({str(e)})"
        
        table_data = [
            ("Provider", str(provider)),
            ("Domain", domain),
            ("IP Address", ip_address),
            ("Port", str(port)),
            ("Ping Status", ping_status),
            ("Average Ping Time", avg_ping_time),
        ]        
        
        rows_html = ""
        for metric, details in table_data:
            rows_html += f"<tr><td class='td-metric'>{metric}</td><td>{details}</td></tr>\n"        
        
        html_snippet = f"""
        <h2><b>{provider}</b></h2>
        <table>
            <thead>
                <tr><th>Metric</th><th>Details</th></tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        """
        return html_snippet    

    
    @staticmethod
    def print_all_providers_info_html() -> str:
        """Returns a full HTML page with ping reports for all providers (except exemptions)."""
        exemptions = [LLMProvider.OLLAMA_LOCAL, LLMProvider.VLLM]
        snippets = []
        for provider in LLMProvider:
            if provider in exemptions:
                continue
            snippets.append(LLMProviderStats.ping_provider_html(provider))
        
        # Combine all snippets into a single full HTML page
        all_snippets_html = "\n".join(snippets)
        
        html_page = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bitrecs Verified Providers</title>
            <style>
                body {{
                    font-family: 'Courier New', monospace;
                    background-color: #f4f4f4;
                    color: #333;
                    margin: 10px;
                    padding: 10px;
                    text-align: center;
                }}
                h1 {{
                    color: #555;
                }}
                h2 {{
                    color: #666;
                    margin-top: 40px;
                }}
                table {{
                    width: 95%;
                    margin: 20px auto;
                    border-collapse: collapse;
                    background-color: #fff;
                    box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: left;
                }}
                th {{
                    background-color: #f2f2f2;
                    font-weight: bold;
                }}
                tr:nth-child(even) {{
                    background-color: #f9f9f9;
                }}
                .td-metric {{
                    width: 20%;
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            <h1>Bitrecs Verified Providers</h1>
            {all_snippets_html}
        </body>
        </html>
        """
        return html_page