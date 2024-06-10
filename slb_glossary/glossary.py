from typing import Tuple, List, Dict, Union, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.options import ArgOptions
import math
import time
import sys
import os
import functools
from difflib import get_close_matches
from urllib.parse import quote
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.wpewebkit.webdriver import WebDriver
from selenium.webdriver.wpewebkit.service import Service
from selenium.common.exceptions import WebDriverException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.safari.options import Options as SafariOptions
import enum
import atexit
from dataclasses import dataclass, astuple, asdict

from .exceptions import NetworkError, BrowserException, BrowserNotInstalled


__all__ = [
    "Browser",
    "Language",
    "SearchResult",
    "Glossary",
]


class Browser(enum.Enum):
    """Supported browsers for the glossary search"""
    CHROME = "Chrome"
    EDGE = "Edge"
    FIREFOX = "Firefox"
    CHROMIUM_EDGE = "Chromium Edge"
    SAFARI = "Safari"


class Language(enum.Enum):
    """Available languages for the glossary search"""
    ENGLISH = "en"
    SPANISH = "es"


def get_glossary_base_url(lang_code: str="en") -> str: 
    """
    Get the base url for the glossary

    :param lang_code: The language code to use. Defaults to 'en' for English. Other supported language is Spanish - 'es'
    :return: The base url for the glossary
    """
    return f'https://glossary.slb.com/{lang_code}/search'



@dataclass(slots=True, frozen=True, order=True, eq=True, repr=True)
class SearchResult:
    """Holds the search result of a term in the glossary"""
    term: str
    """The term found in the glossary"""
    definition: Optional[str]
    """The definition of the term found in the glossary"""
    grammatical_label: Optional[str]
    """Basically the part of speech of the term"""
    topic: Optional[str]
    """The topic the term is related to or the topic under which the definition was found"""
    url: Optional[str]
    """The url of the page containing the definition of the term in the glossary"""

    def astuple(self) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
        """Return the search result as a tuple"""
        return astuple(self)
    
    def asdict(self) -> Dict[str, Union[str, None]]:
        """Return the search result as a dictionary"""
        return asdict(self)



class Glossary(object):
    """
    Search the SLB glossary programmatically using Selenium. 
    
    For optimum performance, use Chrome browser and make sure you have a fast internet connection.

    NOTE: Speed of execution is dependent on your internet connection. If your internet connection is slow,
    you may want to increase the value of the implicit_wait_time attribute.
    """
    implicit_wait_time = 3.0
    """The implicit wait time for the Selenium driver"""
    no_of_terms_per_tab = 12
    """
    The expected number of terms in one term on the glossary page. This is largely subject to change,
    and is dependent on the glossary website.
    """
    saver_class = None
    """
    Preferred search result saver class. Set this if you want override the default saver class
    with a (modified) subclass.
    """
    
    def __init__(
        self, 
        browser: Browser = Browser.CHROME, 
        *,
        open_browser: bool = False,
        page_load_timeout: Optional[int] = None,
        implicit_wait_time: Optional[Union[float, int]] = None,
        language: Language = Language.ENGLISH
    ) -> None:
        """
        Initialize the glossary

        Speed of execution is largely dependent on your internet connection!

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge or safari.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param page_load_timeout: The number of seconds to wait for a page to load before throwing an error
        :param implicit_wait_time: The number of seconds to wait for an element to be found before throwing an error
        :param open_browser: Opens the browser window if set to True. Defaults to False. This is useful if you
        want to see the browser window while the code is executing, probably for debugging purposes.
        Do not close the browser window while code is executing else code execution stops.
        :param language: The language to use for the glossary search. Defaults to English
        """ 
        if not isinstance(browser, Browser):
            raise TypeError('browser must be an instance of `Browser` Enum')

        self.language = language
        self._initialize_browser(
            browser=browser, 
            open_browser=open_browser,
            page_load_timeout=page_load_timeout,
            implicit_wait_time=implicit_wait_time,
        )
        sys.stdout.write(f"\r{type(self).__name__}: Getting available topics and glossary size...\n")
        self._topics, self._size = self.get_topics(get_size=True)
        sys.stdout.write(f"\r{type(self).__name__}: Available topics and glossary size gotten\n")
        # Switch to a new tab after instantiation process is completed
        self.browser.switch_to.new_window('tab')
        self.browser.switch_to.window(self.browser.window_handles[0])
        self.browser.close()
        self.browser.switch_to.window(self.browser.window_handles[-1])
        atexit.register(self.close)

    # Just to enable usage as a context manager
    def __enter__(self) -> 'Glossary':
        return self
    
    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
        return None

    
    @functools.cached_property
    def base_url(self) -> str:
        """Base url for searching for terms in the glossary"""
        return get_glossary_base_url(self.language.value)
    
    @functools.cached_property
    def saver(self):
        """The saver object for saving search results to a file"""
        from .saver import Saver, _Saver

        saver_class: type[_Saver] = type(self).saver_class or Saver
        return saver_class()
        

    def _initialize_browser(
        self, 
        browser: Browser, 
        *, 
        open_browser: bool = False,
        page_load_timeout: Optional[int] = None,
        implicit_wait_time: Optional[Union[float, int]] = None,
    ) -> None:
        """
        Initialize the browser

        :param browser: The browser to use. Must be one of chrome, firefox, chromium edge, edge or safari.
        The browser selected should be one you have installed on your machine and must be supported by selenium
        :param page_load_timeout: The number of seconds to wait for a page to load before throwing an error
        :param implicit_wait_time: The number of seconds to wait for an element to be found before throwing an error
        :param open_browser: Whether to open the browser window or not. Defaults to False. 
        Do not close the browser window while code is executing else code execution stops.
        """
        options = self._get_browser_options(browser)
        # Add headless options if open_browser is False
        if options and not open_browser:
            options = self._add_headless_options(browser, options)
        
        try:
            webdriver_classname = browser.value.replace(" ", "")
            browser_service = _get_browser_service(browser)
            self.browser: WebDriver = getattr(webdriver, webdriver_classname)(options=options, service=browser_service)
        except AttributeError:
            raise BrowserNotInstalled(f'{browser.value} is not installed on your machine')

        if page_load_timeout:
            self.browser.set_page_load_timeout(page_load_timeout)
        self.browser.implicitly_wait(implicit_wait_time or self.implicit_wait_time)
        return None


    def _get_browser_options(self, browser: Browser) -> ArgOptions | None:
        """
        Get necessary options for the given browser. These options are essential to enhance speed and efficiency

        :param browser: The browser to get the options for
        :return: The browser options for the given browser
        """
        options = None
        browser_name = browser.value.lower()
        
        if browser_name == 'chrome':
            options = webdriver.ChromeOptions()
            # Essential options to enhance speed and efficiency
            options.add_argument('--no-sandbox')  # Bypass OS security model
            options.add_argument('--disable-dev-shm-usage')  # Overcome limited resource problems
            options.add_argument('--disable-extensions')  # Disable all extensions
            options.add_argument('--disable-infobars')  # Disable infobars
            options.add_argument('--disable-notifications')  # Disable notifications
            options.add_argument('--disable-popup-blocking')  # Disable popup blocking
            options.add_argument('--disable-background-networking')  # Disable background networking
            options.add_argument('--disable-sync')  # Disable syncing to Google account
            options.add_argument('--disable-translate')  # Disable translation
            options.add_argument('--no-first-run')  # Skip first run wizards
            options.add_argument('--ignore-certificate-errors')  # Ignore certificate errors
            # Disable image loading
            prefs = {"profile.managed_default_content_settings.images": 2}
            options.add_experimental_option("prefs", prefs)

        elif browser_name == 'firefox':
            options = options or webdriver.FirefoxOptions()
            # Set preferences to enhance speed and efficiency
            options.set_preference('dom.webnotifications.enabled', False)  # Disable notifications
            options.set_preference('geo.enabled', False)  # Disable geolocation
            options.set_preference('media.navigator.enabled', False)  # Disable camera access
            options.set_preference('media.peerconnection.enabled', False)  # Disable WebRTC
            options.set_preference('network.cookie.cookieBehavior', 2)  # Block all cookies
            options.set_preference('network.dns.disablePrefetch', True)  # Disable DNS prefetching
            # Disable image loading
            options.set_preference('permissions.default.image', 2)

        elif browser_name in ['edge', 'chromium edge']:
            options = webdriver.EdgeOptions()
            # Essential options to enhance speed and efficiency
            options.add_argument('--no-sandbox')  # Bypass OS security model
            options.add_argument('--disable-dev-shm-usage')  # Overcome limited resource problems
            options.add_argument('--disable-extensions')  # Disable all extensions
            options.add_argument('--disable-infobars')  # Disable infobars
            options.add_argument('--disable-notifications')  # Disable notifications
            options.add_argument('--disable-popup-blocking')  # Disable popup blocking
            options.add_argument('--disable-background-networking')  # Disable background networking
            options.add_argument('--disable-sync')  # Disable syncing to Microsoft account
            options.add_argument('--disable-translate')  # Disable translation
            options.add_argument('--no-first-run')  # Skip first run wizards
            options.add_argument('--ignore-certificate-errors')  # Ignore certificate errors
            # Disable image loading
            prefs = {"profile.managed_default_content_settings.images": 2}
            options.add_experimental_option("prefs", prefs)

        elif browser_name == 'safari':
            options = SafariOptions()
            # Safari has limited options compared to other browsers
            options.set_capability("safari:automaticInspection", True)
            options.set_capability("safari:automaticProfiling", True)
            # Disabling images and some other settings is not straightforward in Safari
        return options
    

    def _add_headless_options(self, browser: Browser, options: ArgOptions) -> ArgOptions:
        """
        Add headless options to the browser options

        :param browser: The browser to add the headless options to
        :param options: The browser options to add the headless options to
        :return: The browser options with the headless options added
        """
        browser_name = browser.value.lower()
        
        if browser_name == 'chrome':
            options.add_argument('--headless=new')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
        elif browser_name == 'firefox':
            options.add_argument('--headless')
        elif browser_name == 'edge':
            options.add_argument('--headless=new')
        elif browser_name == 'chromium edge':
            options.use_chromium = True
            options.add_argument('--headless=new')
        elif browser_name == 'safari':
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
    
    @property
    def closed(self) -> bool:
        """Check if the glossary has been closed or not"""
        try:
            return not self.browser.window_handles
        except WebDriverException:
            # Browser has been closed
            return True
    

    def close(self) -> None:
        """
        Close the glossary and free up resources.
        This should be called after you're done with the glossary.
        """
        if self.closed:
            return
        
        no_of_open_windows = len(self.browser.window_handles)
        # Close all open windows
        for _ in range(no_of_open_windows):
            self.browser.close()
        return None
    

    def _get_element_by_css_selector(self, 
        css_selector: str,
        *,  
        root: Optional[Union[WebDriver, WebElement]] = None, 
        max_retry: int = 3
    ) -> WebElement | None:
        """
        Get the first element with the given css selector

        :param css_selector: The css selector of the element to get
        :param root: The root element to search from. Defaults to None
        :param max_retry: The maximum number of times to retry getting the element. Defaults to 3
        """
        tries = 0
        root = root or self.browser

        while tries < max_retry:
            try:
                return root.find_element(by=By.CSS_SELECTOR, value=css_selector)
            except (
                StaleElementReferenceException, 
                NoSuchElementException
            ) as exc:
                time.sleep(0.8)
                tries += 1
                if tries == max_retry:
                    raise exc


    def _get_elements_by_css_selector(self, 
        css_selector: str,
        *,  
        root: Optional[Union[WebDriver, WebElement]] = None, 
        max_retry: int = 3
    ) -> List[WebElement] | None:
        """
        Get the all elements with the given css selector

        :param css_selector: The css selector of the elements to get
        :param root: The root element to search from. Defaults to None
        :param max_retry: The maximum number of times to retry getting the elements. Defaults to 3
        """
        tries = 0
        root = root or self.browser

        while tries < max_retry:
            try:
                return root.find_elements(by=By.CSS_SELECTOR, value=css_selector)
            except (
                StaleElementReferenceException, 
                NoSuchElementException
            ) as exc:
                time.sleep(0.8)
                tries += 1
                if tries == max_retry:
                    raise exc
                

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
                facet_header = self._get_element_by_css_selector('.CoveoFacet .coveo-facet-header')
            except NoSuchElementException:
                self.load(self.base_url)
                continue
            else:
                break

        time.sleep(0.8)
        # if facet header has content, facet items have been loaded else reload page
        if not facet_header or facet_header.text == '':
            return self.get_topics(get_size=get_size)
        
        discipline_facet_expand_button = self._get_element_by_css_selector('.CoveoFacet .coveo-facet-footer .coveo-facet-more')
        self.browser.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", discipline_facet_expand_button)
        time.sleep(0.8)

        topic_elements = self._get_elements_by_css_selector('#discipline-facet .coveo-facet-value')
        topics_dict = {}
        if not topic_elements:
            return topics_dict
        
        for element in topic_elements:
            try:
                topic_element = self._get_element_by_css_selector(".coveo-facet-value-label .coveo-facet-value-caption", root=element)
                terms_count_element = self._get_element_by_css_selector(".coveo-facet-value-label .coveo-facet-value-count", root=element)
                if not (topic_element and terms_count_element):
                    continue
                
                topic = topic_element.text
                no_of_terms = _text_to_int(terms_count_element.text)
                topics_dict[topic] = no_of_terms
            except NoSuchElementException:
                pass

        if get_size:
            glossary_size_element = self._get_element_by_css_selector('.CoveoQuerySummary .coveo-highlight-total-count')
            if not glossary_size_element:
                return topics_dict, 0
            
            size = _text_to_int(glossary_size_element.text)
            return topics_dict, size
            
        return topics_dict
     

    @staticmethod
    def get_pager_query(tab_number: int = 1, *, terms_per_tab: int = 12) -> str:
        """
        Get the query string for the pager/paginator that will be used to get the terms on the given tab

        :param terms_per_tab: The number of terms per tab
        :param tab_number: The tab number to get the query string for
        :return: The query string for the pager/paginator that will be used to get the terms on the given tab
        """
        if tab_number < 2:
            return ''
        return f'first={terms_per_tab * (tab_number - 1)}&'


    def get_topic_match(self, topic: str) -> str:
        """
        Return an appropriate first match for the given topic in `self.topics_list`

        :param topic: The topic(s) to get a match for. If you have multiple topics, separate them with a comma
        like so: 'Geophysics,Geology'
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
                    sys.stdout.write(f"{type(self).__name__}: No match found for topic: {topic}")
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
    ) -> str:
        """
        Returns the url to search the glossary based on the given parameters

        :param topic: The topic(s) to base the search on. If you want to search for terms under multiple topics,
        separate the topics with a comma. For example, 'Geophysics,Geology'
        
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
    ) -> List[str]:
        """
        Returns a list containing the urls of the page containing the definition(s) 
        of each term found searching by the given filters.

        :param query: The search query
        :param under_topic: What topic(s) should the found terms be related to. Streamline search to the given topic(s).
        If you want to search for terms under multiple topics, separate the topics with a comma. For example, 'Geophysics,Geology'

        NOTE: It is advisable to use a topic that is available on the glossary website.
        If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found,
        no result is returned. To get an idea of the available topics check the properties `topics` or `topics_list`.
        
        :param start_letter: Search for terms that start with this letter
        :param count: The number of terms urls to get. If None, all term urls will be returned
        :return: A list of urls of the terms under the given topic
        """
        if count and count < 1:
            raise ValueError('Count must be greater than 0')
        
        if not under_topic and not(query or start_letter):
            return []

        pager_query: str = self.get_pager_query(tab_number=kwargs.get('tab', 1))
        urls: List[str] = kwargs.get('urls', [])
        retry_count = kwargs.get('retry_count', None)
        is_first_run: bool = urls != [] and retry_count is None
        
        if is_first_run:
            result_text_element = self._get_element_by_css_selector('.CoveoResult .CoveoResultLink')
            if not result_text_element:
                return urls
            old_result_text = result_text_element.text
       
        url = self.get_search_url(
            topic=under_topic, 
            query=query, 
            pager_query=pager_query, 
            start_letter=start_letter
        )
        self.load(url)

        if is_first_run:
            # time.sleep(1)
            # If we're moving to a new tab, ensure page content as changed completely before proceeding to get new urls
            def _results_have_changed() -> bool:
                new_result_text_element = self._get_element_by_css_selector('.CoveoResult .CoveoResultLink')
                if not new_result_text_element:
                    return False
                new_result_text = new_result_text_element.text
                return old_result_text != new_result_text
            
            while _results_have_changed() is False:
                time.sleep(0.8) 

        results_header = self._get_element_by_css_selector('.coveo-results-header')
        if not results_header:
            return urls
        # time.sleep(1)
        # if result header has content, results/page have been loaded else reload page
        if urls == [] and results_header.text == '':
            sys.stdout.write(f"\n{type(self).__name__}: Content not loaded yet. Reloading page...\n")
            return self.get_terms_urls(
                query=query, 
                under_topic=under_topic, 
                start_letter=start_letter, 
                count=count, **kwargs
            )

        try:
            terms_count_element = self._get_element_by_css_selector('.CoveoQuerySummary .coveo-highlight-total-count')
            if not terms_count_element:
                return urls
            total_no_of_terms = _text_to_int(terms_count_element.text)
        except ValueError:
            retry_count: int = kwargs.get('retry_count', 0)
            if retry_count <= 4:
                kwargs['retry_count'] = retry_count + 1
                return self.get_terms_urls(
                    query=query, 
                    under_topic=under_topic, 
                    start_letter=start_letter, 
                    count=count, **kwargs
                )
            sys.stdout.write(f"\n{type(self).__name__}: There seems to be no result on this page!\n")
            return urls
        
        kwargs.pop('retry_count', None) # remove retry_count from kwargs if it exists
        found_term_elements = self._get_elements_by_css_selector('.CoveoResult .CoveoResultLink')
        if not found_term_elements:
            return urls
        max_no_of_tabs = math.ceil(total_no_of_terms / self.no_of_terms_per_tab)
        count = total_no_of_terms if count is None else count

        # Get term detail urls on tab
        found_urls: List[str] = []
        for term_element in found_term_elements:
            href = term_element.get_attribute('href')
            if href:
                found_urls.append(href)
            if len(found_urls) >= count:
                break
        
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


    def get_results_from_url(self, url: str, *, under_topic: Optional[str] = None) -> List[SearchResult] | None:
        """
        Extract the definition(s) of a term from the given url and creates a `slb_glossary.SearchResult` object for each definition

        :param url: The url containing the definitions
        :param under_topic: What topics should the definitions extracted be related to.
        If you want to use multiple topics, separate the topics with a comma. For example, 'Drilling,Geology'
        
        NOTE: It is advisable to use a topic that is available on the glossary website. 
        To get an idea of the available topics check the properties `topics` or `topics_list` 
        
        :return: A list of tuples containing the term name and its definition
        """
        if under_topic:
            under_topic = self.get_topic_match(under_topic)
        self.load(url)
        
        term_name_element = self._get_element_by_css_selector(".row .small-12 h1 strong")
        term_detail_elements = self._get_elements_by_css_selector('.content-two-col__text')

        if not (term_name_element and term_detail_elements):
            return None
        term_name = term_name_element.text
        results = []

        for detail_element in term_detail_elements:
            sub_detail_elements = detail_element.find_elements(by=By.CSS_SELECTOR, value='p')
            term_definition_sub = sub_detail_elements[0].text
            term_definition = sub_detail_elements[2].text if sub_detail_elements[1].text == "" else sub_detail_elements[1].text
            grammatical_label_abbreviation = term_definition_sub.split()[1]
            grammatical_label = _full_grammatical_label(self.language, grammatical_label_abbreviation)

            if under_topic and under_topic.lower() in term_definition_sub.lower():
                result = SearchResult(term_name, term_definition, grammatical_label, under_topic, url)
                results.append(result)
                return results
            else:
                topic = term_definition_sub.split('.')[-1].strip().removesuffix(']').removeprefix('[')
                result = SearchResult(term_name, term_definition, grammatical_label, topic, url)
                results.append(result)
        return results


    def get_terms_on(self, topic: str, max_results: Optional[int] = None) -> List[SearchResult]:
        """
        Returns the definitions of terms related to the given topic in the glossary

        :param topic: The topic to base the search on. If you want to search for terms under multiple topics,
        separate the topics with a comma. For example, 'Well completions,Perforating'
        
        NOTE: It is advisable to use a topic that is available on the glossary website.
        If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found,
        no result is returned. To get an idea of the available topics check the properties `topics` or `topics_list`. 
        
        :param max_results: The maximum number of terms to find. If None, all terms will be returned
        :return: A list of tuples containing the terms under the given topic and their definitions

        Note this method returns only the definitions of the terms related to the given topic. 
        If you want to get all the definitions of the terms regardless of topic, use `search(...)` instead.
        """
        term_urls = self.get_terms_urls(under_topic=topic, count=max_results)
        results: List[SearchResult] = []
        for url in term_urls:
            urls_results = self.get_results_from_url(url, under_topic=topic)
            if urls_results:
                results.append(urls_results[0])
        return results


    def search(
        self, 
        query: str, 
        *, 
        under_topic: Optional[str] = None, 
        start_letter: Optional[str] = None, 
        max_results: int = 3
    ) -> List[SearchResult]:
        """
        Search the glossary for terms matching the given query and return their definitions

        :param query: The search query
        :param under_topic: What topics should the definitions extracted be related to. Streamline search to this topic.
        If you want to search for terms under multiple topics, separate the topics with a comma. For example, 'Geophysics,Geology'
        
        NOTE: It is advisable to use a topic that is available on the glossary website.
        If topic is not available it uses the nearest match for topics available on the slb glossary website. If no match is found,
        no result is returned. To get an idea of the available topics check the properties `self.topics` or `self.topics_list`.

        :param start_letter: limit the search to terms starting with the given letter(s)
        :param max_results: The maximum number of results to return. Defaults to 3. If None, all results will be returned
        :return: A list of containing the details on the first `max_results` results of the search. 

        Note that each search results can have multiple definitions on different topics (except a topic is provided).
        Hence, the number of results returned is; `max_results` multiplied by the number of definitions per term.
        """
        terms_urls = self.get_terms_urls(
            query=query, 
            under_topic=under_topic, 
            start_letter=start_letter, 
            count=max_results
        )

        results: List[SearchResult] = []
        for url in terms_urls:
            url_results = self.get_results_from_url(url, under_topic=under_topic or "")
            if url_results:
                results.extend(url_results)
        return results



driver_installations: Dict[Browser, Dict[str, Union[str, None]]] = {
    Browser.CHROME: {
        "driver_path": None,
        "driver_version": None,
    },
    Browser.FIREFOX: {
        "driver_path": None,
        "driver_version": None,
    },
    Browser.EDGE: {
        "driver_path": None,
        "driver_version": None,
    },
    Browser.CHROMIUM_EDGE: {
        "driver_path": None,
        "driver_version": None,
    },
    Browser.SAFARI: {
        "driver_path": None,
        "driver_version": None,
    }
}


def install_driver(browser: Browser, driver_path: str, driver_version: Optional[str] = None) -> None:
    """
    Install the browser driver for Selenium. This affords you an interface
    to specify the path to your browser driver installation, incase
    your program does not run due to the package not finding a suitable browser driver installation.

    :param browser: The browser to install the driver for.
    :param driver_path: The path to the driver executable.
    :param driver_version: The version of the driver executable.
    """
    browser = Browser(browser)
    if browser not in driver_installations:
        raise BrowserException(f"Browser installation for {browser.value} is not supported.")
    

    is_valid_path = os.path.exists(driver_path)
    if not is_valid_path:
        raise FileNotFoundError(f"Driver path '{driver_path}' does not exist.")
    
    driver_installations[browser]["driver_path"] = driver_path
    driver_installations[browser]["driver_version"] = driver_version
    sys.stdout.write(f"Driver was successfully installed for {browser.value}.\n")
    return None

    

def _get_browser_service(browser: Browser) -> Service | None:
    """
    Get the browser service for the given browser, if
    the browser is installed.

    :param browser: The browser to get the service for
    :return: The browser service for the given browser
    """
    if browser not in driver_installations:
        return None
    
    driver_path = driver_installations[browser]["driver_path"]
    if not driver_path:
        return None
    return Service(executable_path=driver_path)



_grammatical_label_mappings: Dict[Language, Dict[str, str]] = {
    Language.ENGLISH: {
        "n.": "Noun",
        "pron.": "Pronoun",
        "vb.": "Verb",
        "adj.": "Adjective",
        "adv.": "Adverb",
        "prep.": "Preposition",
        "conj.": "Conjunction",
        "interj.": "Interjection",
        "art.": "Article",
        "det.": "Determiner",
        "num.": "Numeral",
        "aux.": "Auxiliary Verb",
        "modal": "Modal Verb",
        "participle": "Participle",
        "gerund": "Gerund"
    },
    Language.SPANISH: {
        "s.": "Sustantivo",
        "pron.": "Pronombre",
        "v.": "Verbo",
        "adj.": "Adjetivo",
        "adv.": "Adverbio",
        "prep.": "Preposición",
        "conj.": "Conjunción",
        "interj.": "Interjección",
        "art.": "Artículo",
        "det.": "Determinante",
        "num.": "Número",
        "aux.": "Verbo Auxiliar",
        "modal": "Verbo Modal",
        "participio": "Participio",
        "gerundio": "Gerundio"
    }
}


def _full_grammatical_label(language: Language, abbr: str) -> str:
    """
    Returns the non-abbreviated version of the abbreviated grammatical label
    from `_grammatical_label_mappings`.

    Returns the abbreviation as is, if non-abbreviated version is not available.
    """
    try:
        return _grammatical_label_mappings[language][abbr.lower()]
    except KeyError:
        return abbr


def _text_to_int(text: str) -> int:
    """
    Convert a string to an integer

    :param text: The string to convert to an integer
    :return: The integer representation of the string
    """
    return int(text.replace(",", "").replace(" ", ""))
