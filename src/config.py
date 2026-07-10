import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration loader for the Kickstart Agent."""
    
    @property
    def gemini_api_key(self) -> str:
        """Returns the Gemini API Key.
        
        Raises:
            ValueError: If the GEMINI_API_KEY is not set.
        """
        # We check both GEMINI_API_KEY and GOOGLE_API_KEY as ADK/GenAI SDK might use either
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise ValueError(
                "GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set. "
                "Please set it in your .env file or environment."
            )
        return key

    @property
    def use_vertex_ai(self) -> bool:
        """Returns whether to use Vertex AI. Defaults to False."""
        val = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "0")
        return val.lower() in ("1", "true", "yes")

    @property
    def model_name(self) -> str:
        """Returns the model name to use. Defaults to 'gemini-3.5-flash'."""
        return os.getenv("MODEL_NAME", "gemini-3.5-flash")

    @property
    def pro_model_name(self) -> str:
        """Returns the pro model name to use. Defaults to 'gemini-3.5-flash'."""
        return os.getenv("PRO_MODEL_NAME", "gemini-3.5-flash")

# Global config instance
config = Config()

