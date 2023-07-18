# Schlumberger Petroleum Glossary Finder

This module helps you find the definition of terms in the Schlumberger Petroleum Glossary. This search can be done using several query paramaters such as term name, topics and start letter. The search results are usually returned in a list of tuples containing the term name and its definition. You can find the Schlumberger petroleum glossary [here](https://glossary.slb.com/en/).

> **For optimum performance, it is advisable to use the module with the Chrome browser and a fast and stable internet connection.**

## Installation

* The package can be installed using pip as follows:

```bash
pip install slb-glossary-finder
```

* The package can also be installed from the distribution files as follows:

```bash
git clone https://github.com/ti-oluwa/slb_glossary_finder.git

cd slb_glossary_finder

pip install dist/slb_glossary_finder-<version>-py3-none-any.whl
```

Replace `<version>` with the version of the package you want to install. For example, `0.1.0`. You can check the version of the package you want to install in the `slb_glossary_finder/__init__.py` file.

## Quick Start Guide

To use the package, you need to import the `slb_glossary_finder` module as follows:

```python
from slb_glossary_finder import TermsFinder

finder = TermsFinder()
```

### Finding the definition of a term

To find the definition of a term, you need to use the `search` method of the `TermsFinder` object:

```python
result = finder.search(query='porosity')
definition = result[0][1]
print(definition)

```

Here the term name "porosity" is passed as the `query` parameter to the `search` method. The `search` method returns a list of tuples containing the term name and its definition. The definition of the term is the second element of the first tuple in the list. If the term has multiple definitions, then the `search` method returns a list of tuples containing the term name and its definitions.

### Finding the definition of terms starting with a specific letter

To find the definition of terms starting with a specific letter, you also use the `search` method of the `TermsFinder` object:

```python

result = finder.search(query='', start_letter='p')
for term in result:
    print(f'{term[0]}: ', term[1])
    print('--------------------------')

```

The query parameter is set to an empty string to return all terms starting with the letter 'p' as the query parameter is not optional.

### Finding the definition of terms under a specific topic

Finding the definition of terms under a specific topic is similar to finding the definition of terms starting with a specific letter. The only difference is that the `topic` parameter is used instead of the `start_letter` parameter:

```python

result = finder.search(query='', topic='Drilling')
for term in result:
    print(f'{term[0]}: ', term[1])
    print('--------------------------')

```

An alternative to the `search` method here is the `find_terms_on` method. Read more about the `find_terms_on` method [here](#the-glossarytermsfinder-class).

To search for terms on multiple topics or using multiple start letters, join the topics or start letters with a comma (,) as follows:

```python

result = finder.search(query='', start_letter='p, q, r', topic='Drilling, Geology')
for term in result:
    print(f'{term[0]}: ', term[1])
    print('--------------------------')

```

> **Note:** The parameters of the search method are mutually inclusive. This means that you can use the `query`, `start_letter` and `topic` parameters together (some what like search filters) to find the definition of terms that match all the parameters. For example, you can find the definition of terms starting with the letter 'p' and under the topic 'Drilling' as follows:

```python

result = finder.search(query='', start_letter='p', topic='Drilling')
for term in result:
    print(f'{term[0]}: ', term[1])
    print('--------------------------')

```

### Saving the search results to a file

The search results can be saved to a file using the `saver` attribute of the `TermsFinder` object. The `saver` attribute is an instance of the `TermsSaver` class. The `TermsSaver` class has a `save` method that takes the topic, search results and the file name/path as parameters. The file path/name can be a relative or absolute path. The `save` method saves the search results to the file in the TXT format by default, This can change based on the file extension in the name/path provided. The `save` method returns `True` if the search results are saved successfully and `False` otherwise. The `save` method can be used as follows:

```python

result = finder.search(query='', start_letter='p', topic='Drilling')
saved = finder.saver.save( topic="Drilling", terms=result, filename='search_results.json')
if saved:
    print('Search results saved successfully')
else:
    print('Search results not saved')

```

## Classes

The module contains two classes:

* `GlossaryTermsFinder` alias `TermsFinder`
* `GlossaryTermsSaver` alias `TermsSaver`

### The `GlossaryTermsFinder` class

The `GlossaryTermsFinder` class is used to find the definition of terms in the Schlumberger Petroleum Glossary using Selenium.

>**IMPORTANT INFO: It is advisable to use a topic that is available on the glossary website. If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found, no result is returned. To get an idea of the available topics check the properties `available_topics` or `available_topics_list`. Also `topic` as used in all case scenarios is the same as `Discipline` on the website. Also the valid start letters are letters A to U for now.**

#### Instantiating the `GlossaryTermsFinder` class

The `GlossaryTermsFinder` class can be instantiated as follows:

```python
from slb_glossary_finder import TermsFinder

finder = TermsFinder()

```

Here the `TermsFinder` class is instantiated with default instantiation parameters. The instantiation parameters are as follows:

* `browser` - The browser to use for the search. The default browser is `Chrome`. The browser can be changed to `Firefox` by passing the `browser='Firefox'` parameter to the `TermsFinder` class. The `TermsFinder` class uses the `Chrome` browser by default because the `Chrome` browser is more commonly used than the `Firefox` browser and has been the most stable when used with the `TermsFinder` class.

* `**kwargs` - This includes the following:
  * `page_load_timeout` - The time in seconds to wait for the page to load. The default is based on Selenium's default page load timeout.

  * `implicit_wait_time` - The time in seconds to wait for the element to be found. The default is based on Selenium's default implicit wait time.

  * `explicit_wait_time` - The time in seconds to wait for certain conditions to be met. It is used by the `WebDriverWait` object of the class.

  * `open_browser_window` - A boolean value that determines whether to open a browser window or not. The default is `True`. If `False`, then the browser window is not opened and the search is done in the background.

### Attributes and Properties

The `GlossaryTermsFinder` class has the following attributes:

* `browser` - The browser used for the search. This is an instance of the `selenium.webdriver` class.
* `implicit_wait_time` - The time in seconds to wait for the element to be found. This is a float.
* `explicit_wait_time` - The time in seconds to wait for certain conditions to be met. This is a float. It is used by the `WebDriverWait` object of the class
* `saver` - An instance of the `GlossaryTermsSaver` class. This is used to save the search results to a file. Read more about the `GlossaryTermsSaver` class [here](#the-glossarytermssaver-class).
* `language` - The language of the glossary. This is a string. Can be either 'English' or 'Spanish' - "en" or "es" respectively.
* `base_search_url` - The base URL for the search. This is a string.
* `glossary_size` - The number of terms in the glossary. This is an integer.
* `available_topics` - The topics available on the glossary website. This is a dictionary with the topic name as the key and the number of terms under the topic as the value.
* `available_topics_list` - A list of the topics available on the glossary website. This is a list of strings.
* `wait` - `WebDriverWait` object used to wait for certain conditions to be met. This is an instance of the `selenium.webdriver.support.ui.WebDriverWait` class.

### Methods

The `GlossaryTermsFinder` class has the following methods:

* `search` - This method is used to find the definition of a term, terms starting with a specific letter or terms under a specific topic. The method takes the following parameters:
  * `query` - The term name to search for. This is a string. Note that this parameter is not optional but can be left as an empty string if need be.
  * `start_letter` - The letter to search for terms starting with. This is a string. The default is an empty string.
  * `topic` - The topic to search for terms under. This is a string. The default is an empty string.
  * `max_results` - The maximum number of results to return. This is an integer. The default is None. If None, then all results are returned.

  The `search` method returns a list of tuples containing the term name and its definition. The definition of the term is the second element of the first tuple in the list. If the term has multiple definitions, then the `search` method returns a list of tuples containing the term name and its definitions.

  For simple searches:

  ```python
  # Example
  result = finder.search(query='porosity') # Returns the definition of the term 'porosity'
  result = finder.search(query='', start_letter='p') # Returns the definition of terms starting with the letter 'p'
  result = finder.search(query='', topic='Drilling', max_results=20) # Returns the definition of terms under the topic 'Drilling'

  ```

  For compound searches:

  ```python
  # Example
  result = finder.search(query='', start_letter='p', topic='Drilling') # Returns the definition of terms starting with the letter 'p' and under the topic 'Drilling'
  print(result) # Prints the result

  ```

* `find_terms_on` - This method is used to find the definition of terms under a specific topic. The method takes the following parameters:
  * `topic` - The topic to search for terms under. This is a string. The default is an empty string.
  * `max_results` - The maximum number of results to return. This is an integer. The default is None. If None, then all results are returned.
  
  The `find_terms_on` method returns a list of tuples containing the term name and its definition. The definition of the term is the second element of the first tuple in the list. If a term has multiple definitions, then the `find_terms_on` method returns each definition as a separate tuple in the list.
  
  ```python
  # Example
  result = finder.find_terms_on(topic='Drilling') # Returns the definition of terms under the topic 'Drilling'
  print(result) # Prints the result
  
  ```

* `get_term_urls` - Gets and returns the urls of the terms matching certain criteria. The method takes the following parameters:
  * `topic` - The topic to search for terms under. This is a string and is not optional but can be left as an empty string if need be.
  * `query` - The term name to search for. This is a string.
  * `start_letter` - The letter to search for terms starting with. This is a string. The default is an empty string.
  * `count` - The maximum number of urls to return. This is an integer. The default is None. If None, then all results are returned.

  The `get_term_urls` method returns a list of urls of the terms matching the criteria.

  ```python
  # Example
  urls = finder.get_term_urls(topic='Drilling', query='', start_letter='p') # Returns the urls of terms starting with the letter 'p' and under the topic 'Drilling'
  print(urls) # Prints the urls

  ```

* `get_term_details` - Gets and returns term name and definition(s) in a list of tuples from a given url. The method takes the following parameters:
  * `term_url` - The url of the term to get the details from. This is a string.
  * `topic` - Optional. The topic the search should be based on. This is a string. The default is an empty string.

  ```python
  # Example
  term_details = finder.get_term_details(term_url='https://www.glossary.oilfield.slb.com/en/terms/p/porosity', topic='Drilling') # Returns the term name and definition(s) in a list of tuples
  print(term_details) # Prints the term details

  ```

**Both `get_term_urls` and `get_term_details` methods are used internally by the `search` and `find_terms_on` methods.**

* `get_pager_query` - Returns the query string for the pager/paginator. The method takes the following parameters:
  * `no_of_terms_per_tab` - The number of terms per tab. This is an integer. The default is 12 (as seen on the glossary website). Leave as is except a change as occurred on the glossary website.
  * `tab_number` - The tab number to get the query string for. This is an integer. The default is 1.

  ```python
  # Example
  query_str = finder.get_pager_query(tab_number=2) # Returns the query string for the pager
  print(pager_query) # Prints the pager query

  ```

* `generate_slb_url` - Generate a glossary url for the given parameters. The method takes the following parameters:
  * `topic` - The topic to search for terms under. This is a string. This parameter is not optional but can be left as an empty string if need be.
  * `query` - The term name to search for. This is a string.
  * `start_letter` - The letter to search for terms starting with. This is a string. The default is an empty string.
  * `pager_query` - The query string for the pager. This is a string. The default is an empty string.

  ```python
  # Example
  query_str = finder.get_pager_query(tab_number=5) # Returns the query string for the pager
  url = finder.generate_slb_url(topic='Drilling', query='', start_letter='p', pager_query=query_str) # Returns the url for the given parameters
  print(url) # Prints the url

  ```

* `get_topic_match(self, topic: str)` - Returns the first topic that matches the given topic in `self.available_topics_list`. The method takes the following parameters:
  * `topic` - The topic to get a match for. This is a string.

  ```python
  # Example
  topic = finder.get_topic_match(topic='Well work') # Returns the first topic that matches the given topic
  print(topic) # Prints the topic

  ```

### The `GlossaryTermsSaver` class

The `GlossaryTermsSaver` class is used to save the terms and their definitions to a file.

#### Instantiation

The `GlossaryTermsSaver` class is instantiated as follows:

```python
# Instantiation
saver = GlossaryTermsSaver()
```

#### Attributes

The class has just one attribute:

* `supported_file_extensions` - This is a list of the supported file extensions terms can be saved to. The default is `['csv', 'json', 'txt', 'xlsx']`. This attribute is dependent on the `save_as_*` methods in the class.

#### Methods

The class has the following methods:

* `save` - Saves the terms and their definitions to a file based on file extension. The method takes the following parameters:
  * `topic` - The topic the terms are under.
  * `terms` - The terms to save. This is a list of tuples.
  * `filename` - The name of the file to save the terms to. This is a string. The default is `{topic.title()} Glossary.<ext>`.

  ```python
  # Example
  saver.save(topic="Well completion", terms=[('porosity', 'The percentage of the total volume of a rock or sediment that consists of pore space.'), ('permeability', 'The capacity of a porous rock, sediment, or soil to permit the flow of fluids through its pore spaces.')], filename='glossary_terms.xlsx')
  ```

All other `save_as_*` methods take the same parameters as the `save` method.

* `save_as_csv` - Saves the terms and their definitions to a csv file. The method takes the following parameters:
  
* `save_as_json` - Saves the terms and their definitions to a json file. The method takes the following parameters:

* `save_as_txt` - Saves the terms and their definitions to a text file. The method takes the following parameters:

* `save_as_xlsx` - Saves the terms and their definitions to an excel file. The method takes the following parameters:

#### Adding support for more file extensions

To add support for more file extensions, the following steps should be followed:

* Subclass the `GlossaryTermsSaver` class.

```python
# Subclassing
class MyGlossaryTermsSaver(GlossaryTermsSaver):
    pass
```

* Add a method to the subclass that takes the following parameters:
  * `topic` - The topic the terms are under.
  * `terms` - The terms to save. This is a list of tuples.
  * `filename` - The name of the file to save the terms to. This is a string. The default is `{topic.title()} Glossary.<ext>`.

* The method name should take form of `save_as_<ext>` where `<ext>` is the file extension.

* You can then write your own implementation to save the terms to the file.

```python
# Subclassing
class MyGlossaryTermsSaver(GlossaryTermsSaver):

    def save_as_<ext>(self, topic: str, terms: List[Tuple], filename: str = None):
        filename = filename or f'{topic.title()} Glossary.<ext>'
        # Do something
        return None

# Now you save the terms to a file with the extension <ext>
saver = MyGlossaryTermsSaver()
saver.save(topic="Well completion", terms=[('porosity', 'The percentage of the total volume of a rock or sediment that consists of pore space.'), ('permeability', 'The capacity of a porous rock, sediment, or soil to permit the flow of fluids through its pore spaces.')], filename='glossary_terms.<ext>')

```

## Dependencies

* [seleneium](https://pypi.org/project/selenium/)
* [openpyxl](https://pypi.org/project/openpyxl/)

## Contributing

Contributions are welcome. Please fork the repository and submit a pull request.
