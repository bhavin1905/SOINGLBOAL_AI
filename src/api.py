# src/api.py
import sys
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel

# Add the src directory to Python path
current_dir = Path(__file__).parent
src_dir = current_dir
if src_dir.exists():
    sys.path.insert(0, str(src_dir))

# Try to import the crew with proper error handling
try:
    from soinglobal_smartai.crew import SoinglobalSmartai
    CREW_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import CrewAI components: {e}")
    CREW_AVAILABLE = False

app = FastAPI(title="Soinglobal SmartAI Crew API")


class CrewRequest(BaseModel):
    user_query: str


@app.post("/run-crew")
async def run_crew(request: CrewRequest):
    """
    Run the SoinglobalSmartai crew with a user query.
    """
    if not CREW_AVAILABLE:
        return {
            "query": request.user_query,
            "result": "CrewAI components are not available. Please check your installation.",
            "error": "Module import failed"
        }
    
    try:
        crew_instance = SoinglobalSmartai()
        result = crew_instance.crew(user_query=request.user_query).kickoff()
        return {"query": request.user_query, "result": str(result)}
    except Exception as e:
        return {
            "query": request.user_query,
            "result": f"Error running crew: {str(e)}",
            "error": str(e)
        }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "crew_available": CREW_AVAILABLE,
        "message": "API is running"
    }
