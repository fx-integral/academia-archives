import secrets
from models.eval_type import BitrecsEvaluationType

class EvaluationSetBuilder:    

    @property
    def sample_size(self) -> int:
        return 3

    @property
    def screener_1(self) -> set[BitrecsEvaluationType]:
        return {BitrecsEvaluationType.BITRECS_BASIC_DAILY,
                BitrecsEvaluationType.BITRECS_ARTIFACT_PRICING}
    
    @property
    def screener_2(self) -> set[BitrecsEvaluationType]:
        return {
            BitrecsEvaluationType.BITRECS_SAFE_DAILY,
            BitrecsEvaluationType.BITRECS_HAYSTACK_DAILY,
            BitrecsEvaluationType.BITRECS_QOS_DAILY,
        }
    
    @property
    def validator_a(self) -> set[BitrecsEvaluationType]:
        return {
            BitrecsEvaluationType.BITRECS_PROMPT_DAILY,
            BitrecsEvaluationType.BITRECS_REASON_DAILY,
            BitrecsEvaluationType.BITRECS_SKU_DAILY,
            BitrecsEvaluationType.BITRECS_PREDICT_DAILY,
            BitrecsEvaluationType.BITRECS_INSTACART_DAILY
        }

    def __init__(self, current_block: int = 0):        
        self.current_block = current_block       

    def get_predefined_set(self) -> set[BitrecsEvaluationType]:
        """Combine predefined sets into one."""
        return self.screener_1 | self.screener_2 | self.validator_a
    
    def get_random_selections(self, count: int) -> set[BitrecsEvaluationType]:
        """Select random evaluation types not in predefined sets."""
        full_eval = set(item for item in BitrecsEvaluationType)
        pre_set = full_eval - self.get_predefined_set()
        return set(secrets.choice(list(pre_set)) for _ in range(count))
    
    def build_evaluation_set(self) -> set[BitrecsEvaluationType]:
        """Build the final evaluation set."""
        predefined_set = self.get_predefined_set()
        random_selections = self.get_random_selections(self.sample_size)
        result = predefined_set | random_selections        
        return result

