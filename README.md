# Schlumberger Petroleum Glossary

Search the Schlumberger Petroleum Glossary using Selenium.

**For optimum performance, Use the Chrome browser and a fast and stable internet connection.**

> This is not production stable code and is intended for research or instructional use only.

## Installation

* Install using pip:

```bash
pip install slb-glossary
```

## Dependencies

* [seleneium](https://pypi.org/project/selenium/)
* [openpyxl](https://pypi.org/project/openpyxl/) (for exporting search results to Excel)

## Quick Start

```python
import slb_glossary as slb

# Create a glossary object
glossary = slb.Glossary(slb.Browser.CHROME, open_browser=True)

# Search for a term
results = glossary.search("porosity")

# Print the results
for result in results:
    print(result.asdict())
```

## Usage

**Please note that this is just a brief overview of the module. The modules is heavily documented and you are encouraged to read the docstrings for more information on the various methods and classes.**

> "topics" used in the context of this documentation refers to the subjects or topics in the glossary.

### Instantiate a glossary object

Import the module:

```python
import slb_glossary as slb
```

To use the glossary, you need to create a `Glossary` object. The `Glossary` class takes a few arguments:
    - `browser`: The browser to use. It can be any of the values in the `Browser` enum.
    **Ensure you have the browser selected installed on your machine.**
    - `open_browser`: A boolean indicating whether to open the browser when searching the glossary or not.
    If this is True, a browser window is open when you search for a term. This can be useful for monitoring
    and debugging the search process. If you don't need to see the browser window, set this to False.
    This is analogous to running the browser in headless mode. The default value is False.
    - `page_load_timeout`: The maximum time to wait for a page to load before raising an exception.
    - `implicit_wait_time`: The maximum time to wait for an element to be found before raising an exception.
    - `language`: The language to use when searching the glossary. This ca be any of the values in the `Language` enum.
    Presently, only English and Spanish are supported. The default value is `Language.ENGLISH`.

```python
glossary = slb.Glossary(slb.Browser.CHROME, open_browser=True)
```

### Get all topics/subjects available in the glossary

When you initialize a glossary, the available topics are automatically fetched and stored in the `topics` attribute.

```python
topics = glossary.topics
print(topics)
```

This returns a mapping of the topic to the number of terms under the topic in the glossary

```python
{
    "Drilling": 452,
    "Geology": 518,
    ...
}
```

Use `glossary.topics_list` if you only need a list of the topics in the glossary. `glossary.size` returns the total number of terms in the glossary.

If you need to refetch all topics call `glossary.get_topics()`. Read the method's docstring for more info on its use.

### Get a topic match

Do you have a topic in mind and are not sure if it is in the glossary? Use the `get_topic_match` method to get a topic match. It returns a single topic that best matches the input topic.

```python
topic = glossary.get_topic_match("drill")
print(topic)

# Output: Drilling
```

### Search for a term

Use the `search` method to search for a term in the glossary

```python
results = glossary.search("porosity")
```

This returns a list of [`SearchResult`](#search-results)s for "porosity". You can also pass some optional arguments to the `search` method:
    - `under_topic`: Streamline search to a specific topic
    - `start_letter`: Limit the search to terms starting with the given letter(s)
    - `max_results`: Limit the number of results returned.

### Search for a term under a specific topic

```python
results = glossary.get_terms_on(topic="Well workover")
```

The `get_terms_on` method returns a list of `SearchResult`s for all terms under the specified topic.
The difference between `search` and `get_terms_on` is that `search` searches the entire glossary while `get_terms_on` searches only under the specified topic. Hence, search can contain terms from different topics.

The topic passed need not be an exact match to what is in the glossary. The glossary will choose the closest match to the provided topic that is available in the glossary.

### Search results

Search results are returned as `SearchResult` objects. Each `SearchResult` object has the following attributes:
    - `term`: The term being searched for
    - `definition`: The definition of the term
    - `grammatical_label`: The grammatical label of the term. Basically the part of speech of the term
    - `topic`: The topic under which the term is found
    - `url`: The URL to the term in the glossary

To get the search results as a dictionary, use the `asdict` method.

```python
results = glossary.search("oblique fault")
for result in results:
    print(result.asdict())
```

You could also convert search results to tuples using the `astuple` method.

```python
results = glossary.search("oblique fault")
for result in results:
    print(result.astuple())
```

### Other methods

Some other methods available in the `Glossary` class are:
    - `get_search_url`: Returns the correct glossary url for the given parameters.
    - `get_terms_urls`: Returns the URLs of all terms gotten using the given parameters.
    - `get_results_from_url`: Extracts search results from a given URL. Returns a list of `SearchResult`s.

### Save/export search results to a file

A convenient way to save search results to a file is to use the `saver` attribute of the glossary object.

```python
results = glossary.search("gas lift")
glossary.saver.save(results, "./gas_lift.txt")
```

The `save` method takes a list of `SearchResult`s and the filename or file path to save the results to. The file save format is determined by the file extension. The supported file formats by default are 'xlsx', 'txt', 'csv' and 'json'.
Or check `glossary.saver.supported_file_types`.

### Customizing how results are saved

By default, the `Glossary` class uses a `Saver` class to save search results. This base `Saver` class only supports a few file formats, which should be sufficient. However, if you need to save in an unsupported format. You can subclass the `Saver` class thus;

```python
from typing import List
import slb_glossary as slb

class FooSaver(slb.Saver):
    @staticmethod
    def save_as_xyz(results: List[SearchResult], filename: str):
        # Validate filename or path 
        # Your implementation goes here
        ...
```

Read the docstrings of the `Saver` class to get a good grasp of how to do this. Also, you may read the `slb_glossary.saver` module to get an idea of how you would implement your custom save method.

There are two ways you can use your custom saver class.

1; Create a `Glossary` subclass:

```python
import slb_glossary as slb

class FooGlossary(slb.Glossary):
    saver_class = FooSaver
    ...

glossary = FooGlossary(...)
glossary.saver.save(...)
```

2; Instantiate a saver directly

```python
saver = FooSaver()
saver.save(...)
```

## Contributing

Contributions are welcome. Please fork the repository and submit a pull request.

## Credits

This project was inspired by the 2023/24/25 Petrobowl Team of the Federal University of Petroleum Resources, Effurun, Delta state, Nigeria. It aided the team's preparation for the PetroQuiz and PetroBowl Conpetitions organized by the Society of Petroleum Engineers(SPE).
