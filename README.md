<div align="center">
<a href="https://pandazxx.github.io/mr-deed/latest/"><img src="https://github.com/pandazxx/mr-deed/raw/main/docs/assets/mini-swe-agent-banner.svg" alt="mr-deed banner" style="height: 7em"/></a>
</div>

# The minimal AI software engineering agent

> mr-deed is a fork of [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent), built by the SWE-agent team at Princeton & Stanford. All credit for the original design, research, and implementation goes to them — see [Attribution](#attribution) below.

[![Docs](https://img.shields.io/badge/Docs-green?style=for-the-badge&logo=materialformkdocs&logoColor=white)](https://pandazxx.github.io/mr-deed/latest/)
[![Slack](https://img.shields.io/badge/Slack-4A154B?style=for-the-badge&logo=slack&logoColor=white)](https://join.slack.com/t/swe-bench/shared_invite/zt-36pj9bu5s-o3_yXPZbaH2wVnxnss1EkQ)
[![PyPI - Version](https://img.shields.io/pypi/v/mr-deed?style=for-the-badge&logo=python&logoColor=white&labelColor=black&color=deeppink)](https://pypi.org/project/mr-deed/)

> [!WARNING]
> This is **mr-deed v2**. Read the [migration guide](https://pandazxx.github.io/mr-deed/latest/advanced/v2_migration/). For the previous version, check out the [v1 branch](https://github.com/pandazxx/mr-deed/tree/v1).

`mini` is

- **Minimal**: Just some 100 lines of python for the [agent class](https://github.com/pandazxx/mr-deed/blob/main/src/mr_deed/agents/default.py) (and a bit more for the [environment](https://github.com/pandazxx/mr-deed/blob/main/src/mr_deed/environments/local.py),
[model](https://github.com/pandazxx/mr-deed/blob/main/src/mr_deed/models/litellm_model.py), and [run script](https://github.com/pandazxx/mr-deed/blob/main/src/mr_deed/run/hello_world.py)) — no fancy dependencies!
- **Performant:** Scores >74% on the [SWE-bench verified benchmark](https://www.swebench.com/); starts much faster than Claude Code
- **Deployable:** Supports **local environments**, **docker/podman**, **singularity/apptainer**, **bublewrap**, **contree**, and more
- **Compatible:** Supports all models via **litellm**, **openrouter**, **portkey**, and more. Support for `/completion` and `/response` endpoints, interleaved thinking etc.
- **Tested:** [![Codecov](https://img.shields.io/codecov/c/github/pandazxx/mr-deed?style=flat-square)](https://codecov.io/gh/pandazxx/mr-deed)

<table>
<tr>
<td width="50%">
<a href="https://pandazxx.github.io/mr-deed/latest/usage/mini/"><strong>CLI</strong></a> (<code>mini</code>)
</td>
<td>
<a href="https://pandazxx.github.io/mr-deed/latest/usage/swebench/"><strong>Batch inference</strong></a>
</td>
</tr>
<tr>
<td width="50%">

![mini](https://github.com/SWE-agent/swe-agent-media/blob/main/media/mini/gif/mini.gif?raw=true)

</td>
<td>

![swebench](https://github.com/SWE-agent/swe-agent-media/blob/main/media/mini/gif/swebench.gif?raw=true)

</td>
</tr>
<tr>
<td>
<a href="https://pandazxx.github.io/mr-deed/latest/usage/inspector/"><strong>Trajectory browser</strong></a>
</td>
<td>
<a href="https://pandazxx.github.io/mr-deed/latest/advanced/cookbook/"><strong>Python bindings</strong></a>
</td>
</tr>
<tr>
<td>

![inspector](https://github.com/SWE-agent/swe-agent-media/blob/main/media/mini/gif/inspector.gif?raw=true)

</td>
<td>

```python
agent = DefaultAgent(
    LitellmModel(model_name=...),
    LocalEnvironment(),
)
agent.run("Write a sudoku game")
```

</td>
</tr>
</table>

## Let's get started!

**Option 1:** If you just want to try out the CLI (package installed in anonymous virtual environment)

```bash
pip install uv && uvx mr-deed
# or
pip install pipx && pipx ensurepath && pipx run mr-deed
```

**Option 2:** Install CLI & python bindings in current environment

```bash
pip install mr-deed
mini  # run the CLI
```

**Option 3:** Install from source (developer setup)

```bash
git clone https://github.com/pandazxx/mr-deed.git
cd mr-deed && pip install -e .
mini  # run the CLI
```

Read more in our [documentation](https://pandazxx.github.io/mr-deed/latest/):

* [Quick start guide](https://pandazxx.github.io/mr-deed/latest/quickstart/)
* [Using the `mini` CLI](https://pandazxx.github.io/mr-deed/latest/usage/mini/)
* [Global configuration](https://pandazxx.github.io/mr-deed/latest/advanced/global_configuration/)
* [Yaml configuration files](https://pandazxx.github.io/mr-deed/latest/advanced/yaml_configuration/)
* [Power up with the cookbook](https://pandazxx.github.io/mr-deed/latest/advanced/cookbook/)
* [FAQ](https://pandazxx.github.io/mr-deed/latest/faq/)
* [Contribute!](https://pandazxx.github.io/mr-deed/latest/contributing/)

## Attribution

mr-deed is a fork of [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent), created by Kilian Lieret, Carlos E. Jimenez, and the rest of the SWE-agent team at Princeton & Stanford. All credit for the original design, research, and implementation goes to them — go check out [their repo](https://github.com/SWE-agent/mini-swe-agent) and the rest of [their projects](https://github.com/SWE-agent).

If you found this work helpful, please consider citing the [SWE-agent paper](https://arxiv.org/abs/2405.15793) in your work:

```bibtex
@inproceedings{yang2024sweagent,
  title={{SWE}-agent: Agent-Computer Interfaces Enable Automated Software Engineering},
  author={John Yang and Carlos E Jimenez and Alexander Wettig and Kilian Lieret and Shunyu Yao and Karthik R Narasimhan and Ofir Press},
  booktitle={The Thirty-eighth Annual Conference on Neural Information Processing Systems},
  year={2024},
  url={https://arxiv.org/abs/2405.15793}
}
```
