"""
Token counting utilities for context window management.
"""

import tiktoken
from typing import Dict, List, Tuple


class TokenCounter:
    """Utility class for counting tokens in text content."""

    def __init__(self, model_name: str = "o3-mini"):
        """
        Initialize token counter for a specific model.

        Args:
            model_name: The model to use for token counting (default: o3-mini)
        """
        self.model_name = model_name

        # Model-specific context limits (in tokens)
        self.context_limits = {
            "o3-mini": 200_000,      # o3-mini context limit
            "gpt-4o": 128_000,       # GPT-4o context limit
            "gpt-4": 128_000,        # GPT-4 context limit
            "claude-3-sonnet": 200_000,  # Claude-3 Sonnet context limit
        }

        # Get the appropriate encoding
        try:
            if "o3" in model_name.lower() or "gpt" in model_name.lower():
                self.encoding = tiktoken.encoding_for_model(
                    "gpt-4")  # Use GPT-4 encoding as fallback
            else:
                self.encoding = tiktoken.get_encoding(
                    "cl100k_base")  # Default encoding
        except Exception:
            # Fallback to default encoding if model-specific encoding fails
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in a text string.

        Args:
            text: The text to count tokens for

        Returns:
            Number of tokens in the text
        """
        if not text:
            return 0
        return len(self.encoding.encode(text))

    def estimate_chunk_tokens(self, chunk_data: Dict) -> int:
        """
        Estimate token count for a chunk including metadata.

        Args:
            chunk_data: Dictionary containing chunk information

        Returns:
            Estimated token count for the chunk
        """
        tokens = 0

        # Count source code tokens
        if "source_code" in chunk_data:
            tokens += self.count_tokens(chunk_data["source_code"])

        # Count metadata tokens (estimate 1 token per 4 characters for JSON)
        if "metadata" in chunk_data:
            metadata_str = str(chunk_data["metadata"])
            tokens += len(metadata_str) // 4

        # Add overhead for formatting (headers, structure, etc.)
        overhead = 50  # Conservative estimate for formatting overhead

        return tokens + overhead

    def get_context_limit(self) -> int:
        """Get the context limit for the current model."""
        return self.context_limits.get(self.model_name, 128_000)  # Default to 128k

    def calculate_usage_percentage(self, total_tokens: int) -> float:
        """
        Calculate what percentage of context window is being used.

        Args:
            total_tokens: Total number of tokens being used

        Returns:
            Percentage of context window used (0.0 to 1.0)
        """
        limit = self.get_context_limit()
        return total_tokens / limit

    def get_recommended_limit(self, reserve_for_response: float = 0.25) -> int:
        """
        Get recommended token limit for input, reserving space for response.

        Args:
            reserve_for_response: Percentage of context to reserve for response (default: 25%)

        Returns:
            Recommended maximum tokens for input
        """
        total_limit = self.get_context_limit()
        return int(total_limit * (1 - reserve_for_response))

    def format_token_usage(self, current_tokens: int, additional_tokens: int = 0) -> str:
        """
        Format token usage information for display.

        Args:
            current_tokens: Current token count
            additional_tokens: Additional tokens that would be added

        Returns:
            Formatted string with token usage information
        """
        total_limit = self.get_context_limit()
        recommended_limit = self.get_recommended_limit()

        current_percentage = (current_tokens / total_limit) * 100
        after_percentage = (
            (current_tokens + additional_tokens) / total_limit) * 100

        status = "🟢 SAFE"
        if current_tokens + additional_tokens > recommended_limit:
            status = "🟡 WARNING"
        if current_tokens + additional_tokens > total_limit * 0.9:
            status = "🔴 CRITICAL"

        return (f"{status} | Current: {current_tokens:,} tokens ({current_percentage:.1f}%) | "
                f"After adding: {current_tokens + additional_tokens:,} tokens ({after_percentage:.1f}%) | "
                f"Limit: {total_limit:,} tokens")


def create_token_counter(model_name: str = "o3-mini") -> TokenCounter:
    """
    Create a token counter instance for the specified model.

    Args:
        model_name: The model to create a counter for

    Returns:
        TokenCounter instance
    """
    return TokenCounter(model_name)
