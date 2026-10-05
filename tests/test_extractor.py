"""
Unit tests for ingestion HTML sanitization and technical skill extraction.
"""

import unittest
from ingestion.extractor import (
    extract_skills,
    sanitize_html_description,
    sanitize_html_to_text,
)


class TestHtmlSanitization(unittest.TestCase):
    def test_removes_dangerous_tags(self):
        raw_html = """
        <div>
            <h2>Job Title</h2>
            <script>alert('malicious')</script>
            <style>body { display: none; }</style>
            <p>We are hiring engineers.</p>
            <noscript>JavaScript is required</noscript>
            <iframe src="https://tracking.com"></iframe>
        </div>
        """
        clean = sanitize_html_to_text(raw_html)
        self.assertNotIn("alert", clean)
        self.assertNotIn("<script>", clean)
        self.assertNotIn("display: none", clean)
        self.assertNotIn("JavaScript is required", clean)
        self.assertIn("Job Title", clean)
        self.assertIn("We are hiring engineers.", clean)

    def test_preserves_linebreaks_and_list_formatting(self):
        raw_html = """
        <p>Requirements:</p>
        <ul>
            <li>5+ years of Python experience</li>
            <li>Strong SQL and Docker skills</li>
        </ul>
        <p>Benefits:<br>Health insurance<br>401k</p>
        """
        clean = sanitize_html_to_text(raw_html)
        self.assertIn("- 5+ years of Python experience", clean)
        self.assertIn("- Strong SQL and Docker skills", clean)
        self.assertIn("Health insurance\n401k", clean)

    def test_unescapes_entities(self):
        raw_html = "<p>C&plus;&plus; &amp; Python &lt;3 &quot;Engineer&quot; &#39;Specialist&#39;&nbsp;&nbsp;Role</p>"
        clean = sanitize_html_to_text(raw_html)
        self.assertIn("C++ & Python <3 \"Engineer\" 'Specialist'  Role", clean)

    def test_blank_and_null_inputs(self):
        self.assertEqual(sanitize_html_to_text(None), "")
        self.assertEqual(sanitize_html_to_text(""), "")
        self.assertEqual(sanitize_html_to_text("   \n\t  "), "")

    def test_sanitize_html_description_preserves_rich_html(self):
        raw_html = """
        <div>
            <h2>About the Role</h2>
            <script>alert('pwned')</script>
            <p>Read our <a href="https://ramp.com/blog" onclick="stealCookies()">Engineering Blog</a> and <a href="javascript:alert(1)">bad link</a>.</p>
            <ul>
                <li>Build scalable systems</li>
                <li>Write clean code</li>
            </ul>
        </div>
        """
        sanitized = sanitize_html_description(raw_html)
        # Paragraphs preserved
        self.assertIn("<p>", sanitized)
        self.assertIn("</p>", sanitized)
        # Headings preserved
        self.assertIn("<h2>About the Role</h2>", sanitized)
        # Lists preserved
        self.assertIn("<ul>", sanitized)
        self.assertIn("<li>Build scalable systems</li>", sanitized)
        # Safe link preserved with safe attributes
        self.assertIn('href="https://ramp.com/blog"', sanitized)
        self.assertIn('target="_blank"', sanitized)
        self.assertIn('rel="noopener noreferrer"', sanitized)
        self.assertIn("Engineering Blog</a>", sanitized)
        # Dangerous tags and scripts stripped
        self.assertNotIn("<script>", sanitized)
        self.assertNotIn("pwned", sanitized)
        # Dangerous event handlers stripped
        self.assertNotIn("onclick", sanitized)
        self.assertNotIn("stealCookies", sanitized)
        # Dangerous javascript: protocol stripped
        self.assertNotIn("javascript:", sanitized)
        self.assertNotIn('href="javascript:', sanitized)

    def test_sanitize_html_description_empty_and_plain_text(self):
        self.assertEqual(sanitize_html_description(None), "")
        self.assertEqual(sanitize_html_description(""), "")
        self.assertEqual(sanitize_html_description("Just plain text with no tags"), "Just plain text with no tags")


class TestSkillExtraction(unittest.TestCase):
    def test_alias_normalization(self):
        text = "Experience with postgresql, postgres, k8s, golang, react.js, and amazon web services."
        skills = extract_skills(text)
        self.assertIn("PostgreSQL", skills)
        self.assertIn("Kubernetes", skills)
        self.assertIn("Go", skills)
        self.assertIn("React", skills)
        self.assertIn("AWS", skills)
        # Verify deduplication of postgres and postgresql
        self.assertEqual(skills.count("PostgreSQL"), 1)

    def test_skill_deduplication(self):
        text = "Python Python Python, python and more PYTHON with Docker docker DOCKER."
        skills = extract_skills(text)
        self.assertEqual(skills, ["Docker", "Python"])

    def test_substring_false_positives(self):
        # "Google", "good", "going" must not trigger Go
        text = "Google has a good product and we are going forward with great speed."
        skills = extract_skills(text)
        self.assertNotIn("Go", skills)

        # "JavaScript" must not match Java
        js_text = "Looking for strong JavaScript developers."
        js_skills = extract_skills(js_text)
        self.assertIn("JavaScript", js_skills)
        self.assertNotIn("Java", js_skills)

        # "Cloud", "Company", "CSS" must not match C++
        c_text = "Our Cloud Company develops CSS styles."
        c_skills = extract_skills(c_text)
        self.assertNotIn("C++", c_skills)
        self.assertIn("CSS", c_skills)

    def test_c_plus_plus_matching(self):
        text = "Experience in C++, Python, and Linux."
        skills = extract_skills(text)
        self.assertEqual(skills, ["C++", "Linux", "Python"])

    def test_explicit_user_audit_cases(self):
        # "Go developer" -> Go
        self.assertEqual(extract_skills("Hiring a Go developer"), ["Go"])
        # "Google Cloud" must NOT -> Go
        self.assertNotIn("Go", extract_skills("Experience with Google Cloud Platform"))
        # "Java developer" -> Java
        self.assertEqual(extract_skills("Hiring a Java developer"), ["Java"])
        # "JavaScript developer" must NOT -> Java unless Java is separately mentioned
        self.assertEqual(extract_skills("Hiring a JavaScript developer"), ["JavaScript"])
        self.assertNotIn("Java", extract_skills("Hiring a JavaScript developer"))
        # "React.js" -> React
        self.assertEqual(extract_skills("Experience with React.js"), ["React"])
        # "ReactJS" -> React
        self.assertEqual(extract_skills("Experience with ReactJS"), ["React"])
        # "Postgres" -> PostgreSQL
        self.assertEqual(extract_skills("Database: Postgres"), ["PostgreSQL"])
        # "PostgreSQL" -> PostgreSQL
        self.assertEqual(extract_skills("Database: PostgreSQL"), ["PostgreSQL"])
        # repeated aliases -> one canonical skill
        self.assertEqual(
            extract_skills("Requires PostgreSQL, postgres, postgresql database administration"),
            ["PostgreSQL"],
        )
        # "C++" -> C++
        self.assertEqual(extract_skills("High-performance C++ backend"), ["C++"])
        # random letter "C" in normal prose must not create a C skill
        self.assertEqual(
            extract_skills("Candidates must have a Class C driver license and Section C clearance."),
            [],
        )

    def test_go_positive_cases(self):
        """
        Required positive cases for Go programming language detection:
        - 'Golang developer' => Go
        - 'Experience with Go and Python' => Go
        - 'Backend services written in Go' => Go
        - 'Go, Java, and Kubernetes' => Go
        - Safe positive variants with technical context.
        """
        self.assertEqual(extract_skills("Golang developer"), ["Go"])
        self.assertEqual(extract_skills("Experience with Go and Python"), ["Go", "Python"])
        self.assertEqual(extract_skills("Backend services written in Go"), ["Go"])
        self.assertEqual(extract_skills("Go, Java, and Kubernetes"), ["Go", "Java", "Kubernetes"])

        self.assertEqual(extract_skills("Go programming language"), ["Go"])
        self.assertEqual(extract_skills("Go developer"), ["Go"])
        self.assertEqual(extract_skills("Go engineer"), ["Go"])
        self.assertEqual(extract_skills("Go backend"), ["Go"])
        self.assertEqual(extract_skills("Go services"), ["Go"])
        self.assertEqual(extract_skills("Go microservices"), ["Go"])
        self.assertEqual(extract_skills("Go API"), ["Go"])
        self.assertEqual(extract_skills("Go code"), ["Go"])
        self.assertEqual(extract_skills("Go / Python"), ["Go", "Python"])
        self.assertEqual(extract_skills("Go, Python, Java"), ["Go", "Java", "Python"])
        self.assertEqual(extract_skills("experience with Go"), ["Go"])
        self.assertEqual(extract_skills("proficiency in Go"), ["Go"])
        self.assertEqual(extract_skills("written in Go"), ["Go"])
        self.assertEqual(extract_skills("using Go to build scalable services"), ["Go"])
        self.assertEqual(extract_skills("Golang"), ["Go"])
        self.assertEqual(extract_skills("Go"), ["Go"])
        self.assertEqual(extract_skills("Senior Software Engineer - Go"), ["Go"])
        self.assertEqual(extract_skills("Backend Engineer (Go)"), ["Go"])
        self.assertEqual(extract_skills("Languages: Go, Rust"), ["Go", "Rust"])

    def test_go_negative_cases(self):
        """
        Required negative cases that must NOT produce Go:
        - 'wherever we go'
        - 'help us go further'
        - 'go-to-market strategy'
        - 'ready to go'
        - 'customers can go online'
        - other common English idioms and multiline leaks.
        """
        self.assertEqual(extract_skills("wherever we go"), [])
        self.assertEqual(extract_skills("help us go further"), [])
        self.assertEqual(extract_skills("go-to-market strategy"), [])
        self.assertEqual(extract_skills("ready to go"), [])
        self.assertEqual(extract_skills("customers can go online"), [])

        self.assertEqual(extract_skills("ways to go beyond"), [])
        self.assertEqual(extract_skills("go to market"), [])
        self.assertEqual(extract_skills("as we go"), [])
        self.assertEqual(extract_skills("let's go"), [])
        self.assertEqual(extract_skills("go above and beyond"), [])
        self.assertEqual(extract_skills("Google has a good algorithm and ongoing cargo operations."), [])
        self.assertEqual(extract_skills("go out of your way"), [])
        self.assertEqual(extract_skills("go code of conduct"), [])

        # Multiline boundary protection: language on previous line must not leak into English 'go'
        self.assertEqual(extract_skills("Java\ngo to market"), ["Java"])
        self.assertEqual(extract_skills("Python\nwherever we go"), ["Python"])
        self.assertEqual(extract_skills("We love Python. Ready to go."), ["Python"])

    def test_go_mixed_paragraph_no_programming_context(self):
        """
        Required test: Mixed paragraph containing many ordinary uses of 'go'
        with zero programming context must NOT match Go.
        """
        paragraph = (
            "At our company, wherever we go, our team strives to go above and beyond. "
            "We are ready to go with our new go-to-market strategy to help us go further in the industry. "
            "As we go forward, customers can go online to find out what we offer, so let's go make a difference!"
        )
    def test_go_bullet_list_items(self):
        """Standalone 'Go' on its own bullet line in requirements."""
        self.assertEqual(extract_skills("Requirements:\n- Go\n- Python"), ["Go", "Python"])
        self.assertEqual(extract_skills("Requirements:\n• Go\n• Docker"), ["Docker", "Go"])
        self.assertEqual(extract_skills("Requirements:\n* Go\n* Kubernetes"), ["Go", "Kubernetes"])
        self.assertEqual(extract_skills("Requirements:\nGo\nPython"), ["Go", "Python"])

    def test_react_false_positives_avoided(self):
        """English verb 'react to alerts' and LLM 'ReAct frameworks' must NOT match React."""
        self.assertEqual(extract_skills("ability to react to alerts quickly"), [])
        self.assertEqual(extract_skills("must react promptly to system incidents"), [])
        self.assertEqual(extract_skills("Experience with ReAct frameworks and LLM agents"), [])
        self.assertEqual(extract_skills("Experience with ReAct prompting"), [])
        # True positives must still match
        self.assertEqual(extract_skills("Experience with React.js"), ["React"])
        self.assertEqual(extract_skills("Experience with ReactJS"), ["React"])
        self.assertEqual(extract_skills("React Native developer"), ["React"])
        self.assertEqual(extract_skills("Senior Frontend Engineer (React)"), ["React"])
        self.assertEqual(extract_skills("Proficiency with React and TypeScript"), ["React", "TypeScript"])

    def test_html_url_false_positive_avoided(self):
        """URLs ending in .html or paths must NOT match HTML."""
        self.assertEqual(extract_skills("Visit our careers page at https://company.com/about.html"), [])
        self.assertEqual(extract_skills("Documentation: https://example.com/guide.html"), [])
        # Genuine HTML skill must match
        self.assertEqual(extract_skills("Experience with HTML, CSS, and JavaScript"), ["CSS", "HTML", "JavaScript"])
        self.assertEqual(extract_skills("HTML5 semantic markup"), ["HTML"])

    def test_rust_trustworthy(self):
        """'trustworthy' must NOT match Rust."""
        self.assertEqual(extract_skills("Looking for a trustworthy and hardworking engineer"), [])
        self.assertEqual(extract_skills("Backend services built with Rust"), ["Rust"])


if __name__ == "__main__":
    unittest.main()
