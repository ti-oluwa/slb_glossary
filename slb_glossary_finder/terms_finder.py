from typing import Tuple, List
from selenium import webdriver
from selenium.webdriver.common.by import By
import math
import time
from selenium.webdriver.wpewebkit.webdriver import WebDriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.safari.options import Options as SafariOptions

from .save import GlossaryTermsSaver
from .exceptions import NetworkError, BrowserException, BrowserNotInstalled, BrowserNotSupported


ALLOWED_BROWSERS = webdriver.__all__


class SLBGlossaryTermsFinder:
    """
    Class for finding terms in the SLB glossary using Selenium
    
    :attr wait_duration: The number of seconds to wait for an element to be found before throwing an error

    :attr browser: The browser webdriver instance to be used in finding the terms

    :attr saver: The GlosssaryTermsSaver object to be used in saving the terms found
    """

    wait_duration = 5
    saver = GlossaryTermsSaver()

    def __init__(self, browser: str ='chrome', **kwargs) -> None:
        """
        Initialize the glossary terms finder

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param kwargs: Other keyword arguments
                :kwargs page_load_timeout: The number of seconds to wait for a page to load before throwing an error

                :kwargs wait_duration: The number of seconds to wait for an element to be found before throwing an error

                :kwargs open_window: Whether to open the browser window or not. Defaults to False
        """ 
        return self._init_browser(browser, **kwargs)
        

    def _init_browser(self, browser: str, **kwargs) -> None:
        """
        Initialize the browser

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge, safari, etc.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param kwargs: Other keyword arguments
                :kwargs page_load_timeout: The number of seconds to wait for a page to load before throwing an error

                :kwargs wait_duration: The number of seconds to wait for an element to be found before throwing an error

                :kwargs open_window: Whether to open the browser window or not. Defaults to False
        """
        browser = browser.title().replace(' ', '')
        if browser not in ALLOWED_BROWSERS:
            raise BrowserNotSupported(f'{browser.title()} is not supported by selenium')

        options = self._get_headless_options(browser) if kwargs.get('open_window', False) is False else None
        try:
            self.browser: WebDriver = getattr(webdriver, browser)(options=options)
        except AttributeError:
            raise BrowserNotInstalled(f'{browser.title()} is not installed on your machine')

        if kwargs.get('page_load_timeout', None):
            self.browser.set_page_load_timeout(kwargs.get('page_load_timeout'))
        if kwargs.get('wait_duration', None):
            self.wait_duration = kwargs.get('wait_duration')
            
        self.browser.implicitly_wait(self.wait_duration)


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
        """
        try:
            self.browser.get(url)
        except WebDriverException as e:
            raise NetworkError(e)
        except Exception as e:
            raise BrowserException(e)


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


    @staticmethod
    def generate_slb_url(topic: str, pager_query: str = '', by_start_letter: bool = False, by_topic_and_start_letter: bool = False):
        """
        Generate the url for the given topic

        :param topic: The topic to generate the url for
        :param pager_query: The query string for the pager/paginator. Points to a specific tab. Use the get_pager_query method to get the query string
        :param by_start_letter: Whether to generate the url for the topic by topic's first letter or not. e.g
        if True, the url for the topic 'd' or 'drilling' will be generated as "https://glossary.slb.com/en/search#sort=relevancy&f:TermStartLetterFacet=[D]"

        :param by_topic_and_start_letter: Whether to generate the url for the topic by topic and (topic's first letter or another letter provided) or not. e.g
        if True, the url for the topic "drilling, c" will be generated as "https://glossary.slb.com/en/search#sort=relevancy&f:DisciplineFacet=[Drilling]&f:TermStartLetterFacet=[C]"
        if the topic is just "drilling", the url will be generated as "https://glossary.slb.com/en/search#sort=relevancy&f:DisciplineFacet=[Drilling]&f:TermStartLetterFacet=[D]"

        :raises ValueError: If topic is empty
        :return: The url for the given topic
        """
        if not topic:
            raise ValueError('Topic cannot be empty')

        if by_topic_and_start_letter is True:
            if len(topic.split(',')) > 1:
                topic, start_letter = topic.split(',')
                start_letter = start_letter[0].upper().strip()
            else:
                start_letter = topic[0].upper()
            return f'https://glossary.slb.com/en/search#{pager_query}sort=relevancy&f:DisciplineFacet=[{topic.title()}]&f:TermStartLetterFacet=[{start_letter}]'
        
        if by_start_letter is True:
            start_letter = topic[0].upper()
            return f'https://glossary.slb.com/en/search#{pager_query}sort=relevancy&f:TermStartLetterFacet=[{start_letter}]'
        # Else generate url by topic
        return f'https://glossary.slb.com/en/search#{pager_query}sort=relevancy&f:DisciplineFacet=[{topic.title()}]'


    def get_terms_urls(self, topic: str, count: int = None, **kwargs):
        """
        Get the urls of the terms under the given topic

        :param topic: The topic to get the terms for
        :param count: The number of terms to get. If None, all terms will be returned
        :param kwargs: Other keyword arguments
        :return: A list of urls of the terms under the given topic
        """
        if count and not isinstance(count, int):
            raise TypeError('Invalid type for count')
        if count and count < 1:
            raise ValueError('Count must be greater than 0')
        if not isinstance(topic, str):
            raise TypeError('Invalid type for topic')

        pager_query = self.get_pager_query(tab_number=kwargs.get('tab', 1))
        urls = kwargs.get('urls', [])
        slb_url = self.generate_slb_url(topic, pager_query)

        self._load(slb_url)

        if kwargs.get('urls', None):
            time.sleep(3)
        results_header = self.browser.find_element(by=By.CLASS_NAME, value='coveo-results-header')
        # if result header has content, results have been loaded else reload page
        while results_header.text == '':
            print('Content not loaded yet. Reloading page...')
            return self.get_terms_urls(topic, count)

        total_no_of_terms_found = int(self.browser.find_elements(by=By.CSS_SELECTOR, value='.CoveoQuerySummary .coveo-highlight')[2].text)
        found_terms = self.browser.find_elements(by=By.CSS_SELECTOR, value='.CoveoResult .CoveoResultLink')
        no_of_terms_per_tab = len(found_terms)
        max_no_of_tabs = math.ceil(total_no_of_terms_found / no_of_terms_per_tab)
        count = total_no_of_terms_found if count is None else count
        # Get term detail urls on tab
        urls.extend([ term.get_attribute('href') for term in found_terms[:count] ])
        count -= no_of_terms_per_tab
    
        if count > 0:   # if there are more terms to find
            current_tab = kwargs.get('tab', 1)
            next_tab = current_tab + 1
            if next_tab <= max_no_of_tabs:
                return self.get_terms_urls(topic, count, tab=next_tab, urls=urls)
        return urls


    def get_term_details(self, topic: str, term_url: str):
        """
        Get the details of the term on the given url

        :param topic: The topic to base the search on
        :param term_url: The url of the term to get the details for
        :return: A tuple containing the term name and its definition
        """
        self._load(term_url)
        term_name: str = self.browser.find_element(by=By.CSS_SELECTOR, value=".row .small-12 h1 strong").text
        term_details = self.browser.find_elements(by=By.CSS_SELECTOR, value='.content-two-col__text')
        details = []

        for detail in term_details:
            sub_details = detail.find_elements(by=By.CSS_SELECTOR, value='p')
            term_definition_sub: str = sub_details[0].text
            if len(sub_details) <= 4:
                term_definition: str = sub_details[1].text
            elif len(sub_details) > 4:
                term_definition: str = sub_details[2].text if sub_details[1].text == "" else sub_details[1].text

            if topic and topic.lower() in term_definition_sub.lower():
                details.append((term_name, term_definition))
                return details
            elif topic == "":
                details.append((term_name, f"Under {term_definition_sub.split('.')[-1].strip()} - {term_definition}"))

        if details == []:
            details.append((term_name, ""))
        return details


    def find_terms_on(self, topic: str, count: int = None) -> List[Tuple[str, str]]:
        """
        Find terms on a given topic in the glossary

        :param topic: The topic to base the search on
        :param count: The number of terms to find. If None, all terms will be returned
        :return: A list of tuples containing the terms under the given topic and their definitions
        """
        term_links = self.get_terms_urls(topic, count)
        return [ self.get_term_details(topic, term_link)[0] for term_link in term_links ]


    def search(self, query: str, under_topic: str = None, max_results: int = 3):
        """
        Search the glossary for the given query

        :param query: The query to search for
        :param under_topic: filter the search under the given topic
        :param max_results: The maximum number of results to return. Should be less than or equal to 12
        :return: A list of containing the details on the first `max_results` results of the search. 

        Note that each search results can have multiple definitions on different topics and each definition is a tuple of the term and its definition.
        So the number of results returned is `max_results` multiplied by the number of definitions per result, except a topic is specified in `under_topic`.
        """
        if under_topic and not isinstance(under_topic, str):
            raise TypeError('Invalid type for under_topic')
        if not isinstance(query, str):
            raise TypeError('Invalid type for query')
        
        if max_results > 12:
            max_results = 12
        search_url = f'https://glossary.slb.com/en/search#q={query}'
        if under_topic:
            search_url += f'&f:DisciplineFacet=[{under_topic.title()}]'
        
        self._load(search_url)

        results_header = self.browser.find_element(by=By.CLASS_NAME, value='coveo-results-header')
        # if result header has content, results have been loaded else reload page
        while results_header.text == '':
            print('Content not loaded yet. Reloading page...')
            return self.search(query, under_topic)

        found_terms = self.browser.find_elements(by=By.CSS_SELECTOR, value='.CoveoResult .CoveoResultLink')
        related_terms = [ term for term in found_terms if term.text.lower() in query.lower() or query.lower() in term.text.lower() ]
        result_urls = [ term.get_attribute('href') for term in related_terms[:max_results] ]

        return [ result for url in result_urls for result in self.get_term_details(under_topic or "", url) ]



