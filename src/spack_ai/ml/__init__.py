"""Machine-learning framework for spack-ai.

    data/        TrainingExample schema, JSONL datasets, collectors that harvest
                 examples from agent transcripts and Spack package repositories
    models/      TrainableModel interface + registry (plug the chosen ML software in here)
    training/    TrainingConfig + Trainer (split, fit, evaluate, checkpoint)
    evaluation/  metrics shared with the agent evals (recipe and mapping quality)
    serving.py   load a trained run so skills (or an LLM provider) can use it

See src/spack_ai/ml/README.md.
"""
