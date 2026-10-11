# ConTree

!!! note "ConTree Environment class"

    - [Read on GitHub](https://github.com/pandazxx/mr-deed/blob/main/src/mr_deed/environments/extra/contree.py)
    - Requires [ConTree](https://contree.dev) token

    ??? note "Full source code"

        ```python
        --8<-- "src/mr_deed/environments/extra/contree.py"
        ```

::: mr_deed.environments.extra.contree

This environment executes commands in [ConTree](https://contree.dev) sandboxes using [ConTree SDK](https://github.com/nebius/contree-sdk)

## Setup

1. Install the dependencies:
   ```bash
   pip install "mr-deed[contree]"
   ```

2. Set up ConTree token and base_url:
   ```bash
   export CONTREE_TOKEN="your-contree-token"
   export CONTREE_BASE_URL="your-given-base-url-for-contree"
   ```

## Usage

Run mr-deed like with any other environment:
```
mini-extra swebench \
    --subset verified \
    --split test \
    --workers 100
    --environment-class contree
```

It can be specified both through cli parameter or by setting `environment_class` to `contree` in your swebench.yaml config

{% include-markdown "../../_footer.md" %}

