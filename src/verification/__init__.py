"""SecureSkillHub Verification Pipeline — multi-agent skill verification.

Imports are lazy to avoid loading unused dependencies at module level.
"""


def __getattr__(name: str):
    """Lazy-import verification components on demand."""
    if name == "AgentAMdReader":
        from src.verification.agent_a_md_reader import AgentAMdReader
        return AgentAMdReader
    if name == "AgentBCodeParser":
        from src.verification.agent_b_code_parser import AgentBCodeParser
        return AgentBCodeParser
    if name == "AgentDScorer":
        from src.verification.agent_d_scorer import AgentDScorer
        return AgentDScorer
    if name == "AgentESupervisor":
        from src.verification.agent_e_supervisor import AgentESupervisor
        return AgentESupervisor
    if name == "VerificationPipeline":
        from src.verification.pipeline import VerificationPipeline
        return VerificationPipeline
    raise AttributeError(f"module 'src.verification' has no attribute {name!r}")


__all__ = [
    "AgentAMdReader",
    "AgentBCodeParser",
    "AgentDScorer",
    "AgentESupervisor",
    "VerificationPipeline",
]
