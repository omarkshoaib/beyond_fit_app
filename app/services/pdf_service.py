import markdown2
from weasyprint import HTML, CSS

class PdfService:
    @staticmethod
    def generate_pdf(markdown_content: str) -> bytes:
        html_body = markdown2.markdown(markdown_content)
        
        # Super simple styling wrapper
        html_content = f"""
        <html>
        <head>
            <style>
                body {{
                    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                h1 {{
                    color: #2c3e50;
                    border-bottom: 2px solid #3498db;
                    padding-bottom: 10px;
                }}
                h2, h3 {{
                    color: #34495e;
                }}
                ul {{
                    list-style-type: square;
                }}
                .engine-footer {{
                    margin-top: 40px;
                    padding-top: 10px;
                    border-top: 1px solid #ccc;
                    font-size: 0.8em;
                    color: #7f8c8d;
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            {html_body}
            
            <div class="engine-footer">
                Powered by the Deterministic Coaching Engine (Phase 5)
            </div>
        </body>
        </html>
        """
        
        # Weasyprint generation
        pdf_bytes = HTML(string=html_content).write_pdf()
        return pdf_bytes
