import sys
from pathlib import Path
import asyncio

# Ensure src is on path
project_root = Path(__file__).resolve().parent
src_dir = project_root / "src"
sys.path.insert(0, str(src_dir))

# Import required modules
from novel_to_comic.config import load_config
from novel_to_comic.state import load_state
from novel_to_comic.stages.s1_extract import STAGE
from novel_to_comic.stage_runtime import StageRuntime

async def main():
    project_dir = Path("/Users/jbuiles/Code/canary/projects/63f06b92-a5c6-4f5b-b0e5-c330abe49982/and-all-the-earth-a-grave")
    print(f"Loading config and state from {project_dir}...")
    config, env_file = load_config(project_dir)
    print(f"Loaded config. env_file={env_file}")
    print(f"LiteLLM Base URL: {config.litellm_base_url}")
    print(f"Effective extraction model: {config.effective_extraction_model()}")
    
    state = load_state(project_dir)
    
    def on_event(event):
        print(f"EVENT: {event}")
        
    ctx = StageRuntime(
        name="extract",
        state=state,
        project_dir=project_dir,
        on_event=on_event
    )
    
    print("Running stage 'extract'...")
    try:
        await STAGE.run(config, project_dir, ctx)
        print("Success!")
    except Exception as e:
        print(f"Failure: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
