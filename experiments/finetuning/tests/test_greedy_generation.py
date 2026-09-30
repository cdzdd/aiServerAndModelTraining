from types import SimpleNamespace

from experiments.finetuning import local_api
from transformers import GenerationConfig
from transformers.generation.configuration_utils import GenerationMode
from transformers.generation.utils import GenerationMixin


def loaded_model():
    # The fixed Qwen snapshot enables sampling; Factory creates a fresh per-call config.
    return SimpleNamespace(
        generation_config=GenerationConfig(
            do_sample=True, temperature=0.7, top_k=20, top_p=0.8, transformers_version="4.51.3"
        )
    )


def effective_mode(model):
    requested = GenerationConfig(do_sample=False, max_new_tokens=384)
    prepared, _ = GenerationMixin._prepare_generation_config(model, requested)
    return prepared.get_generation_mode()


def test_real_transformers_model_defaults_override_false_when_it_matches_global_default():
    assert effective_mode(loaded_model()) == GenerationMode.SAMPLE


def test_bridge_enforces_greedy_at_real_transformers_generation_boundary():
    model = loaded_model()
    chat_model = SimpleNamespace(engine=SimpleNamespace(model=model))
    local_api.enforce_greedy(chat_model)
    assert effective_mode(model) == GenerationMode.GREEDY_SEARCH
