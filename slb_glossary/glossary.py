from typing import Tuple, List, Dict, Union, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
import math
import time
import sys
import functools
from difflib import get_close_matches
from urllib.parse import quote
from selenium.webdriver.wpewebkit.webdriver import WebDriver
from selenium.common.exceptions import WebDriverException, NoSuchElementException
from selenium.webdriver.safari.options import Options as SafariOptions

from .saver import GlossaryTermsSaver
from .exceptions import NetworkError, BrowserException, BrowserNotInstalled, BrowserNotSupported


ALLOWED_BROWSERS = webdriver.__all__

def get_glossary_base_url(lang_code: str="en") -> str: 
    """
    Get the base url for the glossary

    :param lang_code: The language code to use. Defaults to 'en' for English. Other supported language is Spanish - 'es'
    :return: The base url for the glossary
    """
    return f'https://glossary.slb.com/{lang_code}/search'



class SLBGlossary:
    """
    Search the SLB glossary programmatically using Selenium. 
    
    For optimum performance, use Chrome browser and make sure you have a fast internet connection.

    NOTE: Speed of execution is dependent on your internet connection speed. If your internet connection is slow,
    you may want to increase the implicit_wait_time and explicit_wait_time attributes.
    """
    implicit_wait_time = 3.0
    no_of_terms_per_tab = 12
    saver = GlossaryTermsSaver()

    def __init__(
        self, 
        browser: str ='Chrome', 
        *,
        open_browser_window: bool = False,
        page_load_timeout: Optional[int] = None,
        implicit_wait_time: Optional[Union[float, int]] = None,
        language: str = "en"
    ) -> None:
        """
        Initialize the glossary

        NOTE: Speed of execution is dependent on your internet connection speed

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge or safari.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param page_load_timeout: The number of seconds to wait for a page to load before throwing an error
        :param implicit_wait_time: The number of seconds to wait for an element to be found before throwing an error
        :param open_browser_window: Whether to open the browser window or not. Defaults to False.
        Do not close the browser window while code is executing else code execution stops.
        :param language: The language to use in finding the terms. Defaults to 'en' for English. Other supported language is Spanish - 'es'
        """ 
        self.language = language
        self._initialize_browser(
            browser=browser, 
            open_browser_window=open_browser_window,
            page_load_timeout=page_load_timeout,
            implicit_wait_time=implicit_wait_time,
        )
        sys.stdout.write(f"\n{self.__class__.__name__}: Getting available topics and glossary size...\n")
        self._topics, self._size = self.get_topics(get_size=True)
        sys.stdout.write(f"\n{self.__class__.__name__}: Available topics and glossary size gotten\n")
        # Switch to a new tab after instantiation process is completed
        self.browser.switch_to.new_window('tab')
        self.browser.switch_to.window(self.browser.window_handles[0])
        self.browser.close()
        self.browser.switch_to.window(self.browser.window_handles[-1])

    
    @functools.cached_property
    def base_url(self) -> str:
        """Base url for searching for terms in the glossary"""
        return get_glossary_base_url(self.language)
        

    def _initialize_browser(
        self, 
        browser: str, 
        *, 
        open_browser_window: bool = False,
        page_load_timeout: Optional[int] = None,
        implicit_wait_time: Optional[Union[float, int]] = None,
    ) -> None:
        """
        Initialize the browser

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param page_load_timeout: The number of seconds to wait for a page to load before throwing an error
        :param implicit_wait_time: The number of seconds to wait for an element to be found before throwing an error
        :param open_browser_window: Whether to open the browser window or not. Defaults to False. 
        Do not close the browser window while code is executing else code execution stops.
        """
        browser = browser.title().replace(' ', '')
        if browser not in ALLOWED_BROWSERS:
            raise BrowserNotSupported(f'{browser.title()} is not supported by selenium')

        options = self._get_headless_options(browser) if open_browser_window is False else None
        try:
            self.browser: WebDriver = getattr(webdriver, browser)(options=options)
        except AttributeError:
            raise BrowserNotInstalled(f'{browser.title()} is not installed on your machine')

        if page_load_timeout:
            self.browser.set_page_load_timeout(page_load_timeout)
        self.browser.implicitly_wait(implicit_wait_time or self.implicit_wait_time)
        return None


    def _get_headless_options(self, browser: str) -> Union[webdriver.ChromeOptions, webdriver.FirefoxOptions, webdriver.EdgeOptions, SafariOptions, None]:
        """
        Get the browser options for the given browser

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        :return: The browser options for the given browser in headless mode
        """
        options = None
        
        if browser.lower() == 'chrome':
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
        elif browser.lower() == 'firefox':
            options = webdriver.FirefoxOptions()
            options.headless = True
        elif browser.lower() == 'edge':
            options = webdriver.EdgeOptions()
            options.add_argument('--headless')
        elif browser.lower() == 'chromiumedge':
            options = webdriver.EdgeOptions()
            options.use_chromium = True
            options.add_argument('--headless')
        elif browser.lower() == 'safari':
            options = SafariOptions()
            # Enable automatic handling of the WebDriver extension
            options.set_capability("safari:automaticInspection", True)
            options.set_capability("safari:automaticProfiling", True)
            # Set headless mode by hiding the browser window
            options.add_argument("-background")
        return options

    
    def load(self, url) -> None:
        """
        Load the given url in the browser

        :param url: The url to load
        :return: True if the url was loaded successfully else False
        :raises NetworkError: If there was a network error
        :raises BrowserException: If there was any other error with the browser
        """
        try:
            self.browser.get(url)
        except WebDriverException as exc:
            raise NetworkError(exc)
        except Exception as exc:
            raise BrowserException(exc)


    @property
    def topics(self) -> Dict[str, int]:
        """
        The topics in the glossary as a dictionary with the topic name as key 
        and the number of terms under the topic as value
        """
        return self._topics
    

    @property
    def topics_list(self) -> List[str]:
        """The topics in the glossary as a list"""
        return list(self._topics.keys())
        

    @property
    def size(self) -> int:
        """Total number of terms in the glossary"""
        return self._size


    def get_topics(self, get_size: bool = False) -> Union[Tuple[Dict, int], Dict]:
        """
        Returns the topics in the glossary as a dictionary of `topic` and `number of terms under the topic`

        :param get_size: Whether to return the total size(number of terms) of the glossary or not. Defaults to False
        :return: The topics in the glossary as a dictionary of `topic` and `number of terms under the topic`
        """
        self.browser.maximize_window() # Maximize window so all elements are visible
        self.load(self.base_url)

        while True:
            try:
                facet_header = self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoFacet .coveo-facet-header')
            except NoSuchElementException:
                self.load(self.base_url)
                continue
            else:
                break

        time.sleep(1)
        # if facet header has content, facet items have been loaded else reload page
        if not facet_header or facet_header.text == '':
            return self.get_topics(get_size=get_size)
        
        discipline_facet_expand_button = self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoFacet .coveo-facet-footer .coveo-facet-more')
        self.browser.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", discipline_facet_expand_button)
        time.sleep(1)

        topic_elements = self.browser.find_elements(by=By.CSS_SELECTOR, value='#discipline-facet .coveo-facet-value')
        topics_dict = {}
        for element in topic_elements:
            try:
                topic = element.find_element(by=By.CSS_SELECTOR, value=".coveo-facet-value-label .coveo-facet-value-caption").text
                no_of_terms = int(element.find_element(by=By.CSS_SELECTOR, value=".coveo-facet-value-label .coveo-facet-value-count").text)
                topics_dict[topic] = no_of_terms
            except NoSuchElementException:
                pass

        if get_size is True:
            size = int(self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoQuerySummary .coveo-highlight-total-count').text.replace(',', ''))
            return topics_dict, size
            
        return topics_dict
     

    @staticmethod
    def get_pager_query(tab_number: int = 1, *, terms_per_tab: int = 12):
        """
        Get the query string for the pager/paginator that will be used to get the terms on the given tab

        :param terms_per_tab: The number of terms per tab
        :param tab_number: The tab number to get the query string for
        :return: The query string for the pager/paginator that will be used to get the terms on the given tab
        """
        if tab_number < 2:
            return ''
        return f'first={terms_per_tab * (tab_number - 1)}&'


    def get_topic_match(self, topic: str):
        """
        Return an appropriate first match for the given topic in `self.topics_list`

        :param topic: The topic to get a match for
        :return: first match for `topic`
        """
        if topic == "":
            return topic
        topics = topic.split(',')
        topic_list = [ topic.lower() for topic in self.topics_list ]

        for index, topic in enumerate(topics):
            topic = topic.strip().lower()
            if topic not in topic_list:
                matches = get_close_matches(topic, topic_list, n=1, cutoff=0.5)
                if not matches:
                    sys.stdout.write(f"{self.__class__.__name__}: No match found for topic: {topic}")
                    return ''
                topics[index] = matches[0]

        topic = ",".join(topics)
        return topic.title()


    def get_search_url(
        self,
        *,
        topic: Optional[str] = None, 
        query: Optional[str] = None,  
        start_letter: Optional[str] = None,
        pager_query: Optional[str] = None
    ):
        """
        Returns the url to search the glossary based on the given parameters

        :param topic: The topic to get the terms for
        
        NOTE: It is advisable to use a topic that is available on the glossary website. 
        To get an idea of the available topics check the properties `topics` or `topics_list`
        
        :param query: The search query to use
        :param start_letter: The first letter of the terms to get
        :param pager_query: The query string for the pager/paginator that will be used to get the terms on the given tab
        :return: The url for the given parameters
        """
        if topic is not None:
            topic = self.get_topic_match(topic)
        if not topic and not(query or start_letter):
            return self.base_url
        if query:
            query = f"q={quote(query)}&"
        if start_letter:
            start_letter = f"&f:TermStartLetterFacet=[{ quote(start_letter[0].upper()) }]"
        if topic:
            topic = f"&f:DisciplineFacet=[{ quote(topic) }]"
        slb_url = f"{self.base_url}#{query or ''}{pager_query or ''}sort=relevancy{topic or ''}{start_letter or ''}"
        return slb_url
        

    def get_terms_urls(
        self,
        *, 
        query: Optional[str] = None,
        under_topic: Optional[str] = None, 
        start_letter: Optional[str] = None, 
        count: Optional[int] = None, 
        **kwargs
    ):
        """
        Returns a list containing the urls of the page containing the definition(s) 
        of each term found searching by the given filters.

        :param query: The search query
        :param under_topic: What topic should the found terms be related to.

        NOTE: It is advisable to use a topic that is available on the glossary website.
        If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found,
        no result is returned. To get an idea of the available topics check the properties `topics` or `topics_list`.
        
        :param start_letter: Search for terms that start with this letter
        :param count: The number of terms urls to get. If None, all term urls will be returned
        :return: A list of urls of the terms under the given topic
        """
        if count and count < 1:
            raise ValueError('Count must be greater than 0')
        
        if under_topic is not None:
            under_topic = self.get_topic_match(under_topic)
        if not under_topic and not(query or start_letter):
            return []

        pager_query: str = self.get_pager_query(tab_number=kwargs.get('tab', 1))
        urls: List[str] = kwargs.get('urls', [])
        retry_count: int | None = kwargs.get('retry_count', None)
        is_first_run: bool = urls != [] and retry_count is None
        
        if is_first_run:
            old_result_text = self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoResult .CoveoResultLink').text
       
        url = self.get_search_url(
            topic=under_topic, 
            query=query, 
            pager_query=pager_query, 
            start_letter=start_letter
        )
        self.load(url)

        if is_first_run:
            time.sleep(1)
            # If we're moving to a new tab, ensure page content as changed completely before proceeding to get new urls
            def results_have_changed() -> bool:
                new_result_text = self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoResult .CoveoResultLink').text
                return old_result_text != new_result_text
            
            while results_have_changed() is False:
                time.sleep(1) 

        results_header = self.browser.find_element(by=By.CLASS_NAME, value='coveo-results-header')
        time.sleep(1)
        # if result header has content, results/page have been loaded else reload page
        if urls == [] and results_header.text == '':
            sys.stdout.write(f"\n{self.__class__.__name__}: Content not loaded yet. Reloading page...\n")
            return self.get_terms_urls(
                query=query, 
                under_topic=under_topic, 
                start_letter=start_letter, 
                count=count, **kwargs
            )

        try:
            total_no_of_terms = int(self.browser.find_element(by=By.CSS_SELECTOR, value='.CoveoQuerySummary .coveo-highlight-total-count').text.replace(',', ''))
        except ValueError:
            retry_count = kwargs.get('retry_count', 0)
            if retry_count <= 4:
                kwargs['retry_count'] = retry_count + 1
                return self.get_terms_urls(
                    query=query, 
                    under_topic=under_topic, 
                    start_letter=start_letter, 
                    count=count, **kwargs
                )
            sys.stdout.write(f"\n{self.__class__.__name__}: There seems to be no result on this page!\n")
            return urls
        
        kwargs.pop('retry_count', None) # remove retry_count from kwargs if it exists
        found_terms = self.browser.find_elements(by=By.CSS_SELECTOR, value='.CoveoResult .CoveoResultLink')
        max_no_of_tabs = math.ceil(total_no_of_terms / self.no_of_terms_per_tab)
        count = total_no_of_terms if count is None else count
        # Get term detail urls on tab
        found_urls = [ term.get_attribute('href') for term in found_terms ][:count]
        urls.extend(found_urls)
        count -= len(found_urls)
    
        if count > 0:# if there are more terms to find
            current_tab = kwargs.get('tab', 1)
            next_tab = current_tab + 1
            kwargs.update({
                'tab': next_tab,
                'urls': urls,
            })
            if next_tab <= max_no_of_tabs:
                return self.get_terms_urls(
                    query=query, 
                    under_topic=under_topic, 
                    start_letter=start_letter, 
                    count=count, 
                    **kwargs
                )
        return urls


    def extract_definitions_from_url(self, url: str, *, under_topic: Optional[str] = None) -> List[Tuple[str, str]]:
        """
        Extract the definition(s) of a term from the given url

        :param url: The url containing the definitions
        :param under_topic: What topics should the definitions extracted be related to.
        
        NOTE: It is advisable to use a topic that is available on the glossary website. 
        To get an idea of the available topics check the properties `topics` or `topics_list` 
        
        :return: A list of tuples containing the term name and its definition
        """
        if under_topic:
            under_topic = self.get_topic_match(under_topic)
        self.load(url)
        
        term_name: str = self.browser.find_element(by=By.CSS_SELECTOR, value=".row .small-12 h1 strong").text
        term_details = self.browser.find_elements(by=By.CSS_SELECTOR, value='.content-two-col__text')
        definitions = []

        for detail in term_details:
            sub_details = detail.find_elements(by=By.CSS_SELECTOR, value='p')
            term_definition_sub: str = sub_details[0].text
            term_definition: str = sub_details[2].text if sub_details[1].text == "" else sub_details[1].text

            if under_topic and under_topic.lower() in term_definition_sub.lower():
                definitions.append((term_name, term_definition))
                return definitions
            else:
                definitions.append((term_name, f"Under {term_definition_sub.split('.')[-1].strip()} - {term_definition}"))

        if definitions == []:
            definitions.append((term_name, ""))
        return definitions


    def get_terms_on(self, topic: str, max_results: Optional[int] = None) -> List[Tuple[str, str]]:
        """
        Returns the definitions of terms related to the given topic in the glossary

        :param topic: The topic to base the search on
        
        NOTE: It is advisable to use a topic that is available on the glossary website.
        If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found,
        no result is returned. To get an idea of the available topics check the properties `topics` or `topics_list`. 
        
        :param max_results: The maximum number of terms to find. If None, all terms will be returned
        :return: A list of tuples containing the terms under the given topic and their definitions

        Note this method returns only the definitions of the terms related to the given topic. 
        If you want to get all the definitions of the terms regardless of topic, use `search(...)` instead.
        """
        term_urls = self.get_terms_urls(under_topic=topic, count=max_results)
        return [ self.extract_definitions_from_url(term_url, under_topic=topic)[0] for term_url in term_urls ]


    def search(
        self, 
        query: str, 
        *, 
        under_topic: Optional[str] = None, 
        start_letter: Optional[str] = None, 
        max_results: int = 3
    ) -> List[str]:
        """
        Search the glossary for terms matching the given query and return their definitions

        :param query: The search query
        :param under_topic: What topics should the definitions extracted be related to.
        
        NOTE: It is advisable to use a topic that is available on the glossary website.
        If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found,
        no result is returned. To get an idea of the available topics check the properties `self.topics` or `self.topics_list`.

        :param start_letter: limit the search to terms starting with the given letter(s)
        :param max_results: The maximum number of results to return. Defaults to 3. If None, all results will be returned
        :return: A list of containing the details on the first `max_results` results of the search. 

        Note that each search results can have multiple definitions on different topics 
        (except a topic is provided) and each definition is a tuple of the term and its definition.
        So the number of results returned is, `max_results` multiplied by the number of definitions per result.
        """
        result_urls = self.get_terms_urls(
            query=query, 
            under_topic=under_topic, 
            start_letter=start_letter, 
            count=max_results
        )  
        return [ result for url in result_urls for result in self.extract_definitions_from_url(url, under_topic=under_topic or "") ]



