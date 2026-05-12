"""
For testing purposes, this script is used to simulate evaluating the performance of a miner.

It generates synthetic data and evaluates the performance of a miner.

It uses the OpenAI API to generate responses and the OpenAILLMAsJudgeEval class to evaluate the performance.

It uses the SimpleOpenAICompletionFn class to generate responses.

It uses the generate_synthetic_samples function to generate synthetic data.
"""

import argparse
import json
import os
import time

from completion import SimpleOpenAICompletionFn
from dotenv import load_dotenv
from eval import OpenAILLMAsJudgeEval
from syntectic import generate_synthetic_samples, simple_base_model_response


def run_eval(miner, eval, dataset_path, num_miners=1):
    """
    Runs evaluation over a dataset of (prompt, base_response) pairs.
    Measures LLM-judged score and response time for multiple miners.
    """
    if dataset_path == "synthetic":
        samples = generate_synthetic_samples()
    else:
        with open(dataset_path) as f:
            samples = [json.loads(line) for line in f if line.strip()]

    total_scores = [0.0 for _ in range(num_miners)]
    total_time = 0.0
    results = []

    for i, sample in enumerate(samples):
        prompt = sample["input"]
        base = simple_base_model_response(prompt)
        miner_responses = []
        response_times = []
        for _ in range(num_miners):
            start = time.time()
            response = miner.get_completion(prompt)
            elapsed = time.time() - start
            miner_responses.append(response)
            response_times.append(elapsed)
            total_time += elapsed
        scores = eval.judge_responses(prompt, base, miner_responses)
        for idx, score in enumerate(scores):
            total_scores[idx] += score
        results.append({
            "prompt": prompt,
            "base": base,
            "responses": miner_responses,
            "response_times": response_times,
            "scores": scores,
        })
        print(f"Sample {i+1}/{len(samples)} | Times: {[f'{t:.2f}s' for t in response_times]} | LLM-Judge Scores: {scores}")

    avg_scores = [s / len(samples) if samples else 0.0 for s in total_scores]
    avg_time = total_time / (len(samples) * num_miners) if samples else 0.0
    print(f"\nEvaluation complete. LLM-Judged Avg Scores: {avg_scores} | Avg. response time: {avg_time:.2f}s")
    return {"avg_scores": avg_scores, "avg_response_time": avg_time, "results": results}

if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description="Evaluate miner responses for score and response time using LLM-as-Judge.")
    parser.add_argument('--dataset', type=str, default="synthetic", help="Path to the dataset JSONL file or 'synthetic' for generated data.")
    parser.add_argument('--judge-model', type=str, default="gpt-4", help="OpenAI model to use as judge (default: gpt-4)")
    parser.add_argument('--num-miners', type=int, default=1, help="Number of miners to simulate (default: 1)")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set.")

    eval = OpenAILLMAsJudgeEval(api_key=api_key, judge_model=args.judge_model)
    miner = SimpleOpenAICompletionFn(api_key=api_key)
    run_eval(miner, eval, args.dataset, num_miners=args.num_miners)
