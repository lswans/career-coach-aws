import asyncio

from coach.schemas import Opportunity
from coach.search import SearchResult, WebSearch
from coach.verify import OfferingCheck, find_in_titles, verify_opportunities
from tests.conftest import FakeChecker, FakeSearch

# The playtest hallucination, with the kind of results a real search returns for it.
INVENTED = Opportunity(title="AWS AI Advocate Certification", action="Earn the AWS AI Advocate certification this quarter",
                       timeframe="this quarter", related_skills=["AWS", "Machine Learning"])
REAL = Opportunity(title="AWS Certified Cloud Practitioner", action="Pass the AWS Certified Cloud Practitioner exam",
                   timeframe="this month", related_skills=["AWS"])
GENERAL = Opportunity(title="Mock interviews", action="Do two live-coding mock interviews each week",
                      timeframe="this week", related_skills=["Interviewing"])
AI_RESULTS = [
    SearchResult("AI Developer Advocate, AWS - LinkedIn", "https://www.linkedin.com/jobs/1", "Developer advocate role"),
    SearchResult("AWS Certified AI Practitioner", "https://aws.amazon.com/certification/certified-ai-practitioner/",
                 "Validate in-demand AI knowledge."),
]
CLOUD_RESULTS = [SearchResult("AWS Certified Cloud Practitioner (CLF-C02)",
                              "https://aws.amazon.com/certification/certified-cloud-practitioner/", "Foundational.")]


def check(opportunities, search, checker):
    events = asyncio.run(_collect(verify_opportunities(opportunities, search=search, model=checker)))
    return events, events[-1]["items"]


async def _collect(gen):
    return [event async for event in gen]


def test_an_invented_certification_is_corrected_to_the_real_one():
    search = FakeSearch({"AI Advocate": AI_RESULTS, "Cloud Practitioner": CLOUD_RESULTS})
    checker = FakeChecker({
        "AI Advocate": OfferingCheck(named="AWS AI Advocate", real_match="AWS Certified AI Practitioner"),
        "Cloud Practitioner": OfferingCheck(named="AWS Certified Cloud Practitioner", real_match=""),
    })
    events, (invented, real, general) = check([INVENTED, REAL, GENERAL], search, checker)

    assert invented.verification == "corrected"
    assert (invented.title, invented.original_title) == ("AWS Certified AI Practitioner", "AWS AI Advocate Certification")
    assert invented.action == "Earn the AWS Certified AI Practitioner certification this quarter"
    assert invented.source_url == AI_RESULTS[1].url
    assert (real.verification, real.source_url) == ("verified", CLOUD_RESULTS[0].url)
    assert general.verification == "general" and len(search.queries) == 2  # general advice is never searched
    assert events[-2] == {"type": "stage", "stage": "verify", "state": "done", "detail": "1 verified, 1 corrected"}


def test_the_model_cannot_vouch_for_a_name_no_result_shows():
    """A sycophantic answer ("it's real") changes nothing: the name must appear in a result title."""
    search = FakeSearch({"AI Advocate": AI_RESULTS})
    for answer in (OfferingCheck(named="AWS AI Advocate", real_match="AWS AI Advocate"),
                   OfferingCheck(named="", real_match="")):  # a lazy answer still gets the credential checked
        _, (item,) = check([INVENTED], search, FakeChecker({"AI Advocate": answer}))
        assert item.verification == "unverified" and item.source_url == ""
    # Seen live with qwen3:1.7b: it "names" the real certification instead of the one the step invented.
    swapped = OfferingCheck(named="AWS Certified AI Practitioner", real_match="AWS Certified AI Practitioner")
    _, (item,) = check([INVENTED], search, FakeChecker({"AI Advocate": swapped}))
    assert item.verification == "corrected" and item.original_title == INVENTED.title


def test_matching_needs_the_distinctive_words_in_order():
    assert find_in_titles("AWS AI Advocate", AI_RESULTS) is None  # "AI Developer Advocate" is not a match
    assert find_in_titles("AWS Certified AI Practitioner certification", AI_RESULTS) == AI_RESULTS[1]
    assert find_in_titles("AWS Certification", AI_RESULTS) is None  # nothing distinctive to look for


def test_only_pages_about_an_offering_can_vouch_for_it():
    """Seen live: "Cloud Computing Course" was 'verified' by Wikipedia's "Cloud Computing (horse)"."""
    horse = SearchResult("Cloud Computing (horse) - Wikipedia", "https://en.wikipedia.org/wiki/Cloud_Computing_(horse)", "")
    courses = SearchResult("Best Cloud Computing Courses Online", "https://www.coursera.org/courses?query=cloud", "")
    cs50 = SearchResult("CS50: Introduction to Computer Science", "https://cs50.harvard.edu/x/", "")
    assert find_in_titles("Cloud Computing Course", [horse]) is None
    assert find_in_titles("Cloud Computing Course", [horse, courses]) == courses
    assert find_in_titles("CS50", [cs50]) == cs50  # a plain title still counts on a learning site
    forum = SearchResult("AWS AI Advocate certification? : r/AWSCertifications", "https://www.reddit.com/r/x/1", "")
    blog = SearchResult("How to become an AWS AI advocate at work", "https://aws.amazon.com/blogs/ml/advocate/", "")
    exam_page = SearchResult("AWS Solutions Architect Associate", "https://aws.amazon.com/certification/certified-solutions-architect-associate/", "")
    assert find_in_titles("AWS AI Advocate", [forum, blog]) is None
    assert find_in_titles("AWS Solutions Architect Associate", [exam_page]) == exam_page  # a certification URL counts


def test_chat_replies_are_checked_for_names_nothing_backs_up():
    """Seen live: the coach told a student to take the "AWS Certified Advanced Networking and Security exam"."""
    from coach.verify import names_in_reply, unbacked_names

    reply = ("Congratulations on passing your AWS Cloud Practitioner exam! Next, take the AWS Certified Advanced "
             "Networking and Security exam, or the **AWS Certified Machine Learning Engineer - Associate** [1].")
    assert names_in_reply(reply) == ["AWS Cloud Practitioner exam", "AWS Certified Advanced Networking and Security exam",
                                     "AWS Certified Machine Learning Engineer - Associate"]
    sources = [SearchResult("AWS Certified Machine Learning Engineer - Associate", "https://aws.amazon.com/certification/x/", "")]
    search = FakeSearch({"Advanced Networking": [
        SearchResult("AWS Certified Advanced Networking - Specialty", "https://aws.amazon.com/certification/y/", "")]})
    message = "I passed my AWS Cloud Practitioner exam! What next?"
    flagged = asyncio.run(unbacked_names(reply, message, sources, search))
    assert flagged == ["AWS Certified Advanced Networking and Security exam"]  # typed by the user, or cited: not flagged
    assert search.queries == ["AWS Certified Advanced Networking and Security exam"]
    assert asyncio.run(unbacked_names(reply, message, sources, FakeSearch(down=True))) == []  # can't check is not "invented"
    # Seen live: a quietly rate-limited search returns nothing, which must not brand a real cert as invented.
    assert asyncio.run(unbacked_names(reply, message, sources, FakeSearch({}))) == []
    assert names_in_reply("Next, the AWS Certified Developer - Associate.") == ["AWS Certified Developer - Associate"]

    _, (item,) = check([INVENTED], FakeSearch({}), FakeChecker())
    assert item.verification == "unchecked"
    # A certification from the person's own evidence is theirs: no search, no flag.
    own = FakeSearch()
    assert asyncio.run(unbacked_names("Keep going with the AWS Certified Cloud Practitioner exam.", "What now?", [],
                                      own, "Evidence: AWS Certified Cloud Practitioner (exam scheduled)")) == []
    assert own.queries == []


def test_search_off_or_down_marks_named_steps_unchecked():
    events, (item, general) = check([INVENTED, GENERAL], WebSearch("off", None), FakeChecker())
    assert (item.verification, general.verification) == ("unchecked", "general")
    assert events[0]["state"] == "skipped" and "off" in events[0]["detail"]

    events, (item,) = check([INVENTED], FakeSearch(down=True), FakeChecker())
    assert item.verification == "unchecked"
    assert "not checked" in events[-2]["detail"]



def test_the_persons_own_project_is_not_flagged_or_corrected():
    """Seen with Claude Haiku: "Take your Course Review Classifier ..." tripped the course detector."""
    own = Opportunity(title="Deploy your classifier on AWS",
                      action="Serve your Course Review Classifier as an API on AWS Lambda",
                      timeframe="this quarter", related_skills=["AWS"])
    courses = [SearchResult("Machine Learning Classification Course", "https://www.coursera.org/learn/ml-classification", "")]
    checker = FakeChecker({"classifier": OfferingCheck(named="Course Review Classifier",
                                                       real_match="Machine Learning Classification Course")})
    resume = "Projects: Course Review Classifier (scikit-learn, TF-IDF features) predicts ratings from reviews."

    async def run(known):
        return [e async for e in verify_opportunities([own], search=FakeSearch({"classifier": courses}),
                                                      model=checker, known=known)][-1]["items"][0]

    assert asyncio.run(run(resume)).verification == "general"
    # Without the documents the same step would be "corrected" to a stranger's course, the bug this prevents.
    assert asyncio.run(run("")).verification == "corrected"

    # Seen live: when the search came back empty, the same step said "Not checked". Theirs needs no check.
    async def no_results(step, known):
        return [e async for e in verify_opportunities([step], search=FakeSearch({}), model=checker,
                                                      known=known)][-1]["items"][0].verification

    assert asyncio.run(no_results(own, resume)) == "general"
    assert asyncio.run(no_results(own, "")) == "unchecked"
    exam = Opportunity(title="Finish the Course Review Classifier, then book the AWS exam", action="Do it",
                       timeframe="this month", related_skills=[])
    assert asyncio.run(no_results(exam, resume)) == "unchecked"  # "exam" is still a named offering to check
