from pydantic import BaseModel

class MinerSubmission(BaseModel):    
    created_at: str
    github_account: str
    gist_id: str
    hotkey: str    
    signature: str

    def to_dict(self):
        return self.model_dump()
    

class GistInfo(BaseModel):
    created_at: str
    gist_id: str    
    github_account: str
    hotkey: str
    block: int

    def to_dict(self):
        return self.model_dump()