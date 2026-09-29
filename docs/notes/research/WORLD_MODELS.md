# Jev and screen decisions

Research date: September 22, 2026.

## Recommendation

Build the local voice connection first. Keep screen capture, screen interpretation, decisions, and drawing as separate components.
Then add an optional Jev adapter for decisions with a fixed set of possible answers.
This recommendation follows the evidence below. No model ran during this research.

TypeSafe AI's Jev is the strongest match for the user's reference to a new model.
The company announced it on September 15, 2026.
It describes Jev as a System One decision model. The announcement does not establish it as a visual world model.
The user did not supply a link, so the intended identity remains unconfirmed.
[TypeSafe announcement](https://typesafe.ai/blog/introducing-system-one-models-and-jev).

## Jev: useful after screen interpretation

Jev accepts text and structured state. It does not accept images, audio, or video.
Thus, TalkToMe needs another component to convert a screen into text or structured fields.
Possible sources include accessibility data and optical character recognition (OCR).
The OCR proposal is an integration recommendation, not a Jev capability.
[State documentation](https://docs.typesafe.ai/concepts/state).

Jev returns choices, scores, or probabilities for yes/no questions.
The caller defines the possible answers. Jev evaluates independent questions together.
For example, an adapter could ask which visible button matches a spoken request.
It could also decide whether a selected screen region needs a label.
These are proposed tests, not demonstrated TalkToMe features.
[TypeSafe introduction](https://docs.typesafe.ai/introduction).

The current model is `jev-1.13.0`. The documented price is $0.042 per million input tokens, with no output charge.
The documented limits are 64,000 tokens per request and 32,000 tokens for state plus the longest question.
The service uses `POST /v1/systemone`.
These values can change. An experiment should record the exact model version.
[Model documentation](https://docs.typesafe.ai/models).

TypeSafe reports response times of 70–500 milliseconds. Its published tests generally ran from laptops on the US West Coast.
Its Doom demonstration uses structured text state, not screenshots.
These figures do not establish the complete delay from screen capture to a desktop action in India.
[TypeSafe announcement](https://typesafe.ai/blog/introducing-system-one-models-and-jev).

The official materials examined here do not supply model weights, local hardware requirements, or a license for local model distribution.
The public organization lists client and integration projects. Public client code does not establish public model weights.
Treat Jev as a hosted service unless TypeSafe supplies a separate local release.
[TypeSafe repositories](https://github.com/typesafe-ai), [model documentation](https://docs.typesafe.ai/models).

Correct output types do not guarantee correct decisions.
TypeSafe documents weaknesses with arithmetic, indirect questions, irrelevant context, and hostile instructions inside input data.
Screen coordinates and geometry should remain code operations.
A decision adapter should include an unknown result when the supplied choices do not fit.
[Known model limits](https://docs.typesafe.ai/model-jaggedness/jev-1.13).

## JEPA is a different model family

Joint-Embedding Predictive Architecture (JEPA) learns representations by predicting missing information in a shared representation space.
Video JEPA (V-JEPA) applies this approach to video.
The first V-JEPA release uses a Creative Commons NonCommercial license.
Its published focus is physical perception and future planning research.
[Meta's V-JEPA introduction](https://ai.meta.com/blog/v-jepa-yann-lecun-ai-model-video-joint-embedding-predictive-architecture/).

Meta supplies source code and checkpoints for V-JEPA 2, V-JEPA 2-AC, and V-JEPA 2.1.
V-JEPA 2 checkpoints contain 300 million to 1 billion parameters.
V-JEPA 2.1 checkpoints contain 80 million to 2 billion parameters.
The repository uses the MIT license for most code, with Apache 2.0 terms for specified files.
It recommends NVIDIA CUDA support. Its demonstration assumes a graphics processing unit (GPU).
The repository also notes a macOS problem with its `decord` dependency.
[Official repository](https://github.com/facebookresearch/vjepa2).

V-JEPA 2-AC predicts outcomes conditioned on robot actions.
Its published examples include reaching, grasping, and moving objects with a robot arm.
The examined repository supplies no desktop graphical user interface (GUI) benchmark or measured Mac screen-decision delay.
This evidence supports physical-world research. It does not establish a ready desktop controller.
[Official repository](https://github.com/facebookresearch/vjepa2).

## UI-JEPA: screen research with unavailable models

Apple's user interface JEPA (UI-JEPA) predicts user intent from recorded screen activity.
Its task is to describe intent, not to select desktop clicks or draw on a screen.
Apple releases datasets and download code, but the repository explicitly excludes the models.
The code uses the Apple Sample Code License.
The data uses the Creative Commons Attribution-NonCommercial-NoDerivatives license.
[Apple repository](https://github.com/apple-aiml-research/ml-ui-jepa).

The paper reports a 6.6-fold latency improvement over Claude 3.5 Sonnet for its intent task.
That ratio does not establish a millisecond target for TalkToMe.
The reported system has 4.4 billion parameters. Training details specify NVIDIA A100 hardware with 80 GB of memory.
These are training details, not minimum inference requirements.
The paper reports weaker results on unfamiliar applications and limitations with detailed text recognition.
[UI-JEPA paper, results and Appendix B](https://arxiv.org/html/2409.04081v1).

## NanoJev: an open experiment

NanoJev is a separate community project inspired by Jev.
It uses Qwen3-0.6B and decision heads. Public source code and model files are available.
The model card lists the MIT license for source code and retains the upstream license for the Qwen model.
Its load example uses CUDA. The card does not establish Mac performance.
Its published tests cover Maze, Snake, and two ViZDoom tasks through structured observations.
Those results do not establish desktop GUI accuracy or screenshot understanding.
[NanoJev model card](https://huggingface.co/C-Tianyu/NanoJev).

This project could help test a local decision adapter later.
It needs a separate desktop dataset and measurements before it becomes a product dependency.
The published source includes a persistent local inference service.
[NanoJev repository](https://github.com/TianyuCodings/NanoJev).

## Proposed integration

The following design is a recommendation for this repository, not an implemented model connection.

| Component | Responsibility |
| --- | --- |
| Desktop application | Capture speech and selected screen context |
| Screen interpreter | Supply text, element identifiers, and element bounds |
| External agent | Understand the request and choose the larger task |
| Optional decision adapter | Select among known elements or actions |
| Drawing component | Render shapes in the selected display coordinate system |

The screen snapshot should include a timestamp, a display identifier, and the display scale.
Element identifiers should refer to that snapshot.
The drawing component should reject coordinates from an obsolete snapshot or a different display.
These rules make the screen connection useful with any agent or decision model.

For a Jev experiment, keep remote processing optional and visible in the application.
The local voice connection should work without a TypeSafe account.
When the adapter cannot select an answer, return control to the external agent.

## Measurements before adoption

1. Collect representative screen tasks from the applications that the user uses.
2. Record the correct element and intended action for each task.
3. Measure accuracy with the current external agent alone.
4. Measure accuracy with the optional decision adapter.
5. Measure the median and 95th-percentile delay from screen capture to visible feedback.
6. Record interpretation time, network time, model time, and drawing time separately.
7. Measure performance on changed screens, missing elements, and ambiguous requests.
8. Record memory use and power use for each local model.

A fast model call can still produce a slow screen interaction.
Adopt a decision adapter only when the complete measurements improve the intended tasks.
