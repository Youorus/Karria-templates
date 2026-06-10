
from pathlib import Path
import asyncio

# Import the actual API client and metadata loader
from template_generator.client import KarriaAPIClient, AuthError
from template_generator.submit_template import load_metadata_from_infos, load_template_files, validate_payload

class SubmissionService:
    def __init__(self):
        # The client will be instantiated on-demand within the async method
        pass

    async def submit_template(self, template_id: str):
        """
        Wraps the call to the real template submission logic.
        - Loads files and metadata from the template directory.
        - Validates the payload.
        - Submits using the KarriaAPIClient.
        """
        template_path = Path("outputs") / template_id
        if not template_path.is_dir():
            raise FileNotFoundError(f"Template directory not found: {template_path}")

        # 1. Load metadata and determine if there's a cover letter
        meta = load_metadata_from_infos(template_path)
        with_lm = (template_path / "lm").is_dir()

        # 2. Validate payload before attempting to load files
        errors = validate_payload(meta, with_lm)
        if errors:
            raise ValueError(", ".join(errors))

        # 3. Load all required files into memory
        files = load_template_files(template_path, with_lm=with_lm)

        # 4. Initialize the client and submit
        try:
            async with KarriaAPIClient() as client:
                # The submit_full_template method takes all metadata and file bytes as arguments.
                result = await client.submit_full_template(**meta, **files, with_cover_letter=with_lm)
            return result
        except AuthError as e:
            # Provide a more user-friendly error for auth issues
            raise ConnectionRefusedError(f"Authentication failed: {e}. Check your credentials.") from e
        except Exception as e:
            # Catch other potential errors (HTTP errors, etc.)
            raise IOError(f"Failed to submit to Karria API: {e}") from e


submission_service = SubmissionService()
