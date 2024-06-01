# Schlumberger Petroleum Glossary

Search the Schlumberger Petroleum Glossary using Selenium.

> **For optimum performance, it is advisable to use the module with the Chrome browser and a fast and stable internet connection.**

## Installation

* The package can be installed using pip as follows:

```bash
pip install slb-glossary
```

## Dependencies

* [seleneium](https://pypi.org/project/selenium/)
* [openpyxl](https://pypi.org/project/openpyxl/)

## Quick Start

```python
from slb_glossary import Glossary, Browser

# Create a glossary object
glossary = Glossary(Browser.CHROME)

# Search for a term
results = glossary.search("porosity")

# Print the results
for result in results:
    print(result.asdict())
```

<!-- ## Usage

### Searching for a term

To begin, create a `Glossary` object and call the `search` method with the term you want to search for.

```python
from slb_glossary import Glossary

glossary = Glossary()
results = glossary.search("porosity")
``` -->

## Contributing

Contributions are welcome. Please fork the repository and submit a pull request.
