"""#### Contains class for finding glossary terms in the SLB glossary."""

from typing import Tuple, List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
import math
import time
from difflib import get_close_matches
from urllib.parse import quote
from selenium.webdriver.wpewebkit.webdriver import WebDriver
from selenium.common.exceptions import WebDriverException, NoSuchElementException
from selenium.webdriver.safari.options import Options as SafariOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .save import GlossaryTermsSaver
from .exceptions import NetworkError, BrowserException, BrowserNotInstalled, BrowserNotSupported


ALLOWED_BROWSERS = webdriver.__all__
base_search_url = lambda lang_code="en": f'https://glossary.slb.com/{lang_code}/search'


class GlossaryTermsFinder:
    """
    ### Class for finding terms in the SLB glossary using Selenium. For optimum performance, use Chrome browser and make sure you have a fast internet connection.
    
    :attr implicit_wait_time: The number of seconds to wait for an element to be found before throwing an error

    :attr explicit_wait_time: The number of seconds to wait for certain conditions to be met before throwing an error.
    It is used by the `WebDriverWait` object of the class

    :attr browser: The browser webdriver instance to be used in finding the terms

    :attr saver: The GlosssaryTermsSaver object to be used in saving the terms found

    :attr language: The language to use in finding the terms. Defaults to 'en' for English.
    Other supported language is Spanish - 'es'

    #### NOTE: Speed of execution is dependent on your internet connection speed. If your internet connection is slow,
    you may want to increase the implicit_wait_time and explicit_wait_time attributes.
    """

    implicit_wait_time = 5.0
    explicit_wait_time = 5.0
    no_of_terms_per_tab = 12
    saver = GlossaryTermsSaver()
    language = "en"


    def __init__(self, browser: str ='Chrome', **kwargs) -> None:
        """
        Initialize the glossary terms finder

        #### NOTE: Speed of execution is dependent on your internet connection speed

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param kwargs: Other keyword arguments
                :kwarg page_load_timeout: The number of seconds to wait for a page to load before throwing an error

                :kwarg implicit_wait_time: The number of seconds to wait for an element to be found before throwing an error

                :kwarg open_browser_window: Whether to open the browser window or not. Defaults to False.
                Do not close the browser window while code is executing else code execution stops.

                :kwarg explicit_wait_time: The number of seconds to wait for certain conditions to be met before throwing an error.
                It is used by the `WebDriverWait` object of the class

                :kwarg language: The language to use in finding the terms. Defaults to 'en' for English. Other supported language is Spanish - 'es'
        """ 
        self.language = kwargs.pop('language', self.language)
        self._init_browser(browser, **kwargs)
        print(f"\n{self.__class__.__name__}: Getting available topics and glossary size...\n")
        self._available_topics, self._glossary_size = self._get_topics(get_size=True)
        print(f"\n{self.__class__.__name__}: Available topics and glossary size gotten\n")
        # Switch to a new tab after instantiation process is completed
        self.browser.switch_to.new_window('tab')
        self.browser.switch_to.window(self.browser.window_handles[0])
        self.browser.close()
        self.browser.switch_to.window(self.browser.window_handles[-1])

    
    @property
    def base_search_url(self) -> str:
        """Base url for searching for terms in the glossary"""
        return base_search_url(self.language)
        

    def _init_browser(self, browser: str, **kwargs) -> None:
        """
        Initialize the browser

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param kwargs: Other keyword arguments
                :kwargs page_load_timeout: The number of seconds to wait for a page to load before throwing an error

                :kwargs implicit_wait_time: The number of seconds to wait for an element to be found before throwing an error

                :kwargs open_browser_window: Whether to open the browser window or not. Defaults to False. 
                Do not close the browser window while code is executing else code execution stops.
        """
        browser = browser.title().replace(' ', '')
        if browser not in ALLOWED_BROWSERS:
            raise BrowserNotSupported(f'{browser.title()} is not supported by selenium')

        options = self._get_headless_options(browser) if kwargs.get('open_browser_window', False) is False else None
        try:
            self.browser: WebDriver = getattr(webdriver, browser)(options=options)
        except AttributeError:
            raise BrowserNotInstalled(f'{browser.title()} is not installed on your machine')

        if kwargs.get('page_load_timeout', None):
            self.browser.set_page_load_timeout(kwargs.get('page_load_timeout'))
        if kwargs.get('implicit_wait_time', None):
            self.implicit_wait_time = kwargs.get('implicit_wait_time') if kwargs.get('implicit_wait_time') > 0 else self.implicit_wait_time
        if kwargs.get('explicit_wait_time', None):
            self.explicit_wait_time = kwargs.get('explicit_wait_time') if kwargs.get('explicit_wait_time') > 0 else self.explicit_wait_time

        self.browser.implicitly_wait(self.implicit_wait_time)
        self.wait = WebDriverWait(self.browser, self.explicit_wait_time)


    def _get_headless_options(self, browser: str):
        """
        Get the browser options for the given browser

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        :return: The browser options for the given browser in headless mode
        """
        options = None
        match browser.lower():
            case 'chrome':
                options = webdriver.ChromeOptions()
                options.add_argument('--headless')
                options.add_argument('--disable-gpu')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
            case 'firefox':
                options = webdriver.FirefoxOptions()
                options.headless = True
            case 'edge':
                options = webdriver.EdgeOptions()
                options.add_argument('--headless')
            case 'chromiumedge':
                options = webdriver.EdgeOptions()
                options.use_chromium = True
                options.add_argument('--headless')
            case 'safari':
                options = SafariOptions()
                # Enable automatic handling of the WebDriver extension
                options.set_capability("safari:automaticInspection", True)
                options.set_capability("safari:automaticProfiling", True)
                # Set headless mode by hiding the browser window
                options.add_argument("-background")
        return options

    
    def _load(self, url):
        """
        Load the given url in the browser

        :param url: The url to load
        :return: True if the url was loaded successfully else False
        :raises NetworkError: If there was a network error
        :raises BrowserException: If there was any other error with the browser
        """
        try:
            self.browser.get(url)
            
        except WebDriverException as e:
            raise NetworkError(e)
        except Exception as e:
            raise BrowserException(e)


    @property
    def available_topics(self) -> Dict[str, int]:
        """The topics in the glossary as a dictionary with the topic name as key and the number of terms under the topic as value"""
        return self._available_topics
    

    @property
    def available_topics_list(self) -> List[str]:
        """The topics in the glossary as a list"""
        return list(self._available_topics.keys())
        

    @property
    def glossary_size(self) -> int:
        """Total number of terms in the glossary"""
        return self._glossary_size


    def _get_topics(self, get_size: bool = False):
        """
        Returns the topics in the glossary as a dictionary of `topic` and `number of terms under the topic`

        :param get_size: Whether to return the size of the glossary or not. Defaults to False
        :return: The topics in the glossary as a dictionary of `topic` and `number of terms under the topic`
        """
        self.browser.maximize_window() # Maximize window so all elements are visible
        self._load(self.base_search_url)

        facet_header = self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoFacet .coveo-facet-header')
        time.sleep(1.0)
        # if facet header has content, facet items have been loaded else reload page
        if facet_header.text == '':
            return self._get_topics(get_size=get_size)
        
        discipline_facet_expand_button = self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoFacet .coveo-facet-footer .coveo-facet-more')
        self.browser.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", discipline_facet_expand_button)
        time.sleep(1.0)

        topic_elements = self.browser.find_elements(by=By.CSS_SELECTOR, value='#discipline-facet .coveo-facet-value')
        topics_dict = {}
        for element in topic_elements:
            try:
                topic = element.find_element(by=By.CSS_SELECTOR, value=".coveo-facet-value-label .coveo-facet-value-caption").text
                no_of_terms = int(element.find_element(by=By.CSS_SELECTOR, value=".coveo-facet-value-label .coveo-facet-value-count").text)
                topics_dict[topic] = no_of_terms
            except NoSuchElementException:
                pass

        if get_size == True:
            try:
                glossary_size = int(self.browser.find_elements(by=By.CSS_SELECTOR, value='.CoveoQuerySummary .coveo-highlight')[-1].text.replace(',', ''))
                return topics_dict, glossary_size
            except:
                return topics_dict, 0
        return topics_dict
     

    @staticmethod
    def get_pager_query(no_of_terms_per_tab: int = 12, tab_number: int = 1):
        """
        Get the query string for the pager/paginator that will be used to get the terms on the given tab

        :param no_of_terms_per_tab: The number of terms per tab
        :param tab_number: The tab number to get the query string for
        :return: The query string for the pager/paginator that will be used to get the terms on the given tab
        """
        if tab_number < 2:
            return ''
        return f'first={no_of_terms_per_tab * (tab_number - 1)}&'


    def get_topic_match(self, topic: str):
        """
        Return an appropriate first match for the given topic in `self.available_topics_list`

        :param topic: The topic to get a match for
        :return: first match for `topic`
        """
        if topic == "":
            return topic
        topics = topic.split(',')
        topic_list = [ topic.lower() for topic in self.available_topics_list ]

        for index, topic in enumerate(topics):
            topic = topic.strip().lower()
            if topic not in topic_list:
                matches = get_close_matches(topic, topic_list, n=1, cutoff=0.5)
                if not matches:
                    print(f"{self.__class__.__name__}: No match found for topic: {topic}")
                    return ''
                topics[index] = matches[0]

        topic = ",".join(topics)
        return topic.title()


    def generate_slb_url(self, topic: str, query: str = None, pager_query: str = None, start_letter: str = None):
        """
        Generate the url for the given parameters

        :param topic: The topic to get the terms for
        
        NOTE: It is advisable to use a topic that is available on the glossary website. 
        To get an idea of the available topics check the properties `available_topics` or `available_topics_list`
        
        :param query: The search query to use
        :param pager_query: The query string for the pager/paginator that will be used to get the terms on the given tab
        :param start_letter: The first letter of the terms to get
        :return: The url for the given parameters
        """
        topic = self.get_topic_match(topic or "")
        if not topic and not(query or start_letter):
            return self.base_search_url
        if query:
            query = f"q={quote(query)}&"
        if start_letter:
            start_letter = f"&f:TermStartLetterFacet=[{ quote(start_letter[0].upper()) }]"
        if topic:
            topic = f"&f:DisciplineFacet=[{ quote(topic) }]"
        slb_url = f"{self.base_search_url}#{query or ''}{pager_query or ''}sort=relevancy{topic or ''}{start_letter or ''}"
        return slb_url
        

    def get_terms_urls(self, topic: str, query: str = None, start_letter: str = None, count: int = None, **kwargs):
        """
        Get the urls of the terms under the given topic

        :param topic: The topic to get the term urls for. 

        NOTE: It is advisable to use a topic that is available on the glossary website.
        If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found,
        no result is returned. To get an idea of the available topics check the properties `available_topics` or `available_topics_list`

        :param query: The search query to use
        :param start_letter: The first letter of the terms to get
        :param count: The number of terms to get. If None, all term urls will be returned
        :param kwargs: Other keyword arguments
        :return: A list of urls of the terms under the given topic
        """
        if count and count < 1:
            raise ValueError('Count must be greater than 0')
        
        topic = self.get_topic_match(topic)
        if not topic and not(query or start_letter):
            return []

        pager_query = self.get_pager_query(tab_number=kwargs.get('tab', 1))
        urls = kwargs.get('urls', [])
        if urls and kwargs.get('retry_count', False) == False:
            old_first_result_text = self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoResult .CoveoResultLink').text
       
        url = self.generate_slb_url(topic=topic, query=query, pager_query=pager_query, start_letter=start_letter)
        self._load(url)

        if urls and kwargs.get('retry_count', False) == False:
            time.sleep(1.0)
            # If we're moving to a new tab, ensure page content as changed completely before proceeding to get new urls
            while old_first_result_text == self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoResult .CoveoResultLink').text:
                time.sleep(1.0)                

        results_header = self.browser.find_element(by=By.CLASS_NAME, value='coveo-results-header')
        time.sleep(1.0)
        # if result header has content, results/page have been loaded else reload page
        if urls == [] and results_header.text == '':
            print(f"\n{self.__class__.__name__}: Content not loaded yet. Reloading page...\n")
            return self.get_terms_urls(topic, query=query, start_letter=start_letter, count=count, **kwargs)

        try:
            total_no_of_terms_found = int(self.browser.find_elements(by=By.CSS_SELECTOR, value='.CoveoQuerySummary .coveo-highlight')[-1].text.replace(',', ''))
        except IndexError:
            retry_count = kwargs.get('retry_count', 0)
            if retry_count <= 4:
                kwargs['retry_count'] = retry_count + 1
                return self.get_terms_urls(topic, query=query, start_letter=start_letter, count=count, **kwargs)
            print(f"\n{self.__class__.__name__}: There seems to be no result on this page!\n")
            return urls
        
        kwargs.pop('retry_count', None) # remove retry_count from kwargs if it exists
        found_terms = self.browser.find_elements(by=By.CSS_SELECTOR, value='.CoveoResult .CoveoResultLink')
        no_of_terms_in_tab = len(found_terms)
        max_no_of_tabs = math.ceil(total_no_of_terms_found / self.no_of_terms_per_tab)
        count = total_no_of_terms_found if count is None else count
        # Get term detail urls on tab
        urls.extend([ term.get_attribute('href') for term in found_terms[:count] ])
        count -= no_of_terms_in_tab
    
        if count > 0:   # if there are more terms to find
            current_tab = kwargs.get('tab', 1)
            next_tab = current_tab + 1
            kwargs.update({
                'tab': next_tab,
                'urls': urls,
            })
            if next_tab <= max_no_of_tabs:
                return self.get_terms_urls(topic, query=query, start_letter=start_letter, count=count, **kwargs)
        return urls


    def get_term_details(self, term_url: str, topic: str = ""):
        """
        Get the details of the term on the given url

        :param term_url: The url of the term to get the details for
        :param topic: The topic to base the search on
        
        NOTE: It is advisable to use a topic that is available on the glossary website. 
        To get an idea of the available topics check the properties `available_topics` or `available_topics_list` 
        
        :return: A list of tuples containing the term name and its definition
        """ 
        topic = self.get_topic_match(topic)
        self._load(term_url)
        
        term_name: str = self.browser.find_element(by=By.CSS_SELECTOR, value=".row .small-12 h1 strong").text
        term_details = self.browser.find_elements(by=By.CSS_SELECTOR, value='.content-two-col__text')
        details = []

        for detail in term_details:
            sub_details = detail.find_elements(by=By.CSS_SELECTOR, value='p')
            term_definition_sub: str = sub_details[0].text
            term_definition: str = sub_details[2].text if sub_details[1].text == "" else sub_details[1].text

            if topic and topic.lower() in term_definition_sub.lower():
                details.append((term_name, term_definition))
                return details
            elif topic == "":
                details.append((term_name, f"Under {term_definition_sub.split('.')[-1].strip()} - {term_definition}"))

        if details == []:
            details.append((term_name, ""))
        return details


    def find_terms_on(self, topic: str, max_results: int = None) -> List[Tuple[str, str]]:
        """
        Find terms on a given topic in the glossary

        :param topic: The topic to base the search on
        
        NOTE: It is advisable to use a topic that is available on the glossary website.
        If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found,
        no result is returned. To get an idea of the available topics check the properties `available_topics` or `available_topics_list`. 
        
        :param max_results: The maximum number of terms to find. If None, all terms will be returned
        :return: A list of tuples containing the terms under the given topic and their definitions

        Note this method returns only the definitions of the terms related to the given topic. 
        If you want to get all the definitions of the terms, use `search` instead.
        """
        term_links = self.get_terms_urls(topic, count=max_results)
        return [ self.get_term_details(term_link, topic)[0] for term_link in term_links ]


    def search(self, query: str, topic: str = None, start_letter: str = None, max_results: int = 3):
        """
        Search the glossary for terms matching the given query and other filters

        :param query: The query to search for
        :param topic: filter the search under the given topic
        
        NOTE: It is advisable to use a topic that is available on the glossary website.
        If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found,
        no result is returned. To get an idea of the available topics check the properties `self.available_topics` or `self.available_topics_list`.

        :param start_letter: filter the search to terms starting with the given letter
        :param max_results: The maximum number of results to return. Defaults to 3. If None, all results will be returned
        :return: A list of containing the details on the first `max_results` results of the search. 

        Note that each search results can have multiple definitions on different topics (except a topic is provided) and each definition is a tuple of the term and its definition.
        So the number of results returned is `max_results` multiplied by the number of definitions per result, except a topic is specified in `under_topic`.
        """
        result_urls = self.get_terms_urls(topic, query=query, start_letter=start_letter, count=max_results)  
        return [ result for url in result_urls for result in self.get_term_details(url, topic or "") ]



