"""
Error Solutions Knowledge Base Manager

Provides functionality to load, query, and manage the error solutions knowledge base.
The knowledge base contains training methods and quick fixes for different error types.
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

log = logging.getLogger(__name__)

# Path to the knowledge base JSON file
DATA_DIR = Path(__file__).parent.parent / "data"
KNOWLEDGE_BASE_FILE = DATA_DIR / "error_solutions.json"
PAPER_BIBTEX_FILE = DATA_DIR / "paper_bibtex.json"


class ErrorSolutionsKnowledgeBase:
    """
    Manages the error solutions knowledge base.

    Provides methods to:
    - Load and cache the knowledge base
    - Query solutions for specific error types
    - Add new training methods
    - Update the knowledge base
    """

    _instance: Optional["ErrorSolutionsKnowledgeBase"] = None
    _data: Optional[Dict[str, Any]] = None
    _bibtex_data: Optional[Dict[str, str]] = None
    _parsed_citations: Optional[Dict[str, Dict[str, Any]]] = None
    _last_loaded: Optional[datetime] = None

    def __new__(cls) -> "ErrorSolutionsKnowledgeBase":
        """Singleton pattern to ensure only one instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the knowledge base."""
        if self._data is None:
            self._load()
        if self._bibtex_data is None:
            self._load_bibtex()

    def _load(self) -> None:
        """Load the knowledge base from the JSON file."""
        try:
            if KNOWLEDGE_BASE_FILE.exists():
                with open(KNOWLEDGE_BASE_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                self._last_loaded = datetime.now()
                log.info(
                    "Loaded error solutions knowledge base: %s", KNOWLEDGE_BASE_FILE
                )
            else:
                log.warning("Knowledge base file not found: %s", KNOWLEDGE_BASE_FILE)
                self._data = self._get_default_data()
        except Exception as e:
            log.error("Failed to load knowledge base: %s", e)
            self._data = self._get_default_data()

    def _load_bibtex(self) -> None:
        """Load the paper BibTeX data from the JSON file."""
        try:
            if PAPER_BIBTEX_FILE.exists():
                with open(PAPER_BIBTEX_FILE, "r", encoding="utf-8") as f:
                    self._bibtex_data = json.load(f)
                self._parsed_citations = {}
                for title, bibtex_str in self._bibtex_data.items():
                    self._parsed_citations[title] = self._parse_bibtex(bibtex_str, title)
                log.info("Loaded paper BibTeX data: %d entries", len(self._bibtex_data))
            else:
                log.warning("Paper BibTeX file not found: %s", PAPER_BIBTEX_FILE)
                self._bibtex_data = {}
                self._parsed_citations = {}
        except Exception as e:
            log.error("Failed to load paper BibTeX data: %s", e)
            self._bibtex_data = {}
            self._parsed_citations = {}

    @staticmethod
    def _parse_bibtex(bibtex_str: str, paper_title: str) -> Dict[str, Any]:
        """
        Parse a BibTeX string into a structured citation dict.
        Extracts authors, year, title, venue, DOI, URL, etc.
        """
        citation = {
            "raw_bibtex": bibtex_str,
            "paper_title": paper_title,
        }

        # Extract entry type and cite key
        type_match = re.match(r"@(\w+)\{([^,]+),", bibtex_str)
        if type_match:
            citation["entry_type"] = type_match.group(1).lower()
            citation["cite_key"] = type_match.group(2).strip()

        # Extract fields from bibtex
        field_pattern = re.compile(r"(\w+)\s*=\s*\{([^}]*)\}", re.DOTALL)
        fields = {}
        for match in field_pattern.finditer(bibtex_str):
            key = match.group(1).lower().strip()
            value = match.group(2).strip()
            fields[key] = value

        # Parse authors into list
        if "author" in fields:
            raw_authors = fields["author"]
            # Split by " and " to get individual authors
            author_list = [a.strip() for a in re.split(r"\s+and\s+", raw_authors)]
            citation["authors"] = author_list

            # Build short citation: "Author1 et al." or "Author1 and Author2"
            if len(author_list) == 1:
                last_name = author_list[0].split(",")[0].strip() if "," in author_list[0] else author_list[0].split()[-1].strip()
                citation["short_authors"] = last_name
            elif len(author_list) == 2:
                last1 = author_list[0].split(",")[0].strip() if "," in author_list[0] else author_list[0].split()[-1].strip()
                last2 = author_list[1].split(",")[0].strip() if "," in author_list[1] else author_list[1].split()[-1].strip()
                citation["short_authors"] = f"{last1} and {last2}"
            else:
                last_name = author_list[0].split(",")[0].strip() if "," in author_list[0] else author_list[0].split()[-1].strip()
                citation["short_authors"] = f"{last_name} et al."
        else:
            citation["authors"] = []
            citation["short_authors"] = "Unknown"

        # Extract year
        citation["year"] = fields.get("year", "")

        # Extract title (from bibtex, may differ from paper_title key)
        citation["title"] = fields.get("title", paper_title)

        # Extract venue information
        venue = ""
        if "journal" in fields:
            venue = fields["journal"]
        elif "booktitle" in fields:
            venue = fields["booktitle"]
        citation["venue"] = venue

        # Extract other useful fields
        citation["doi"] = fields.get("doi", "")
        citation["url"] = fields.get("url", "")
        citation["pages"] = fields.get("pages", "")
        citation["volume"] = fields.get("volume", "")
        citation["number"] = fields.get("number", "")
        citation["publisher"] = fields.get("publisher", "")
        citation["eprint"] = fields.get("eprint", "")
        citation["archiveprefix"] = fields.get("archiveprefix", "")

        # Build the short inline citation: [Author et al., Year]
        if citation["year"]:
            citation["inline_citation"] = f"{citation['short_authors']}, {citation['year']}"
        else:
            citation["inline_citation"] = citation["short_authors"]

        # Build full formatted citation (ACL/NeurIPS style)
        parts = []
        if citation["authors"]:
            # Format: "Last1, First1, Last2, First2, ... and LastN, FirstN."
            formatted_authors = "; ".join(citation["authors"][:3])
            if len(citation["authors"]) > 3:
                formatted_authors += " et al."
            parts.append(formatted_authors + ".")

        if citation["year"]:
            parts.append(f"({citation['year']}).")

        if citation["title"]:
            parts.append(f"{citation['title']}.")

        if venue:
            parts.append(f"In {venue}.")

        if citation["pages"]:
            parts.append(f"pp. {citation['pages']}.")

        citation["formatted_citation"] = " ".join(parts)

        return citation

    def get_citation_info(self, reference_title: str) -> Optional[Dict[str, Any]]:
        """
        Get parsed citation info for a paper reference title.
        Handles comma-separated multiple references.
        """
        if not self._parsed_citations:
            return None

        # Direct match
        if reference_title in self._parsed_citations:
            return self._parsed_citations[reference_title]

        # Try to find by partial/fuzzy match
        ref_lower = reference_title.lower().strip()
        for title, citation in self._parsed_citations.items():
            if title.lower().strip() == ref_lower:
                return citation

        return None

    def get_citations_for_reference(self, reference: str) -> List[Dict[str, Any]]:
        """
        Get citation info for a reference string which may contain
        multiple comma-separated paper titles.
        """
        if not reference:
            return []

        # Try direct match first (entire string)
        direct = self.get_citation_info(reference)
        if direct:
            return [direct]

        # Split by comma and try each part
        parts = [p.strip() for p in reference.split(",") if p.strip()]
        if len(parts) <= 1:
            return [direct] if direct else []

        citations = []
        for part in parts:
            c = self.get_citation_info(part)
            if c:
                citations.append(c)

        return citations

    def _enrich_methods_with_citations(self, methods: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Add citation_info field to each method that has a reference.
        """
        enriched = []
        for method in methods:
            method = dict(method)  # Don't mutate original
            ref = method.get("reference")
            if ref:
                citations = self.get_citations_for_reference(ref)
                if citations:
                    method["citation_info"] = citations
            enriched.append(method)
        return enriched

    def _get_default_data(self) -> Dict[str, Any]:
        """Return default minimal data structure."""
        return {
            "version": "1.0.0",
            "last_updated": datetime.now().isoformat(),
            "error_types": {},
            "difficulty_levels": {
                "beginner": {"label": "Beginner", "color": "#22c55e"},
                "intermediate": {"label": "Intermediate", "color": "#f59e0b"},
                "advanced": {"label": "Advanced", "color": "#ef4444"},
            },
            "categories": {},
        }

    def _save(self) -> bool:
        """Save the knowledge base to the JSON file."""
        try:
            # Ensure data directory exists
            DATA_DIR.mkdir(parents=True, exist_ok=True)

            # Update last_updated timestamp
            self._data["last_updated"] = datetime.now().strftime("%Y-%m-%d")

            with open(KNOWLEDGE_BASE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)

            log.info("Saved error solutions knowledge base")
            return True
        except Exception as e:
            log.error("Failed to save knowledge base: %s", e)
            return False

    def reload(self) -> None:
        """Force reload the knowledge base from disk."""
        self._load()
        self._load_bibtex()

    def get_all_error_types(self) -> List[str]:
        """Get list of all error types in the knowledge base."""
        if not self._data:
            return []
        return list(self._data.get("error_types", {}).keys())

    def get_error_type_info(self, error_type: str) -> Optional[Dict[str, Any]]:
        """Get full information for a specific error type."""
        if not self._data:
            return None

        error_types = self._data.get("error_types", {})
        # Try exact match first
        if error_type in error_types:
            return error_types[error_type]

        # Try case-insensitive match
        for key, value in error_types.items():
            if key.lower() == error_type.lower():
                return value

        return None

    def get_quick_fixes(self, error_type: str) -> List[str]:
        """Get quick fix suggestions for an error type."""
        info = self.get_error_type_info(error_type)
        if not info:
            return []
        return info.get("quick_fixes", [])

    def get_training_methods(
        self,
        error_type: str,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get training methods for an error type.

        Args:
            error_type: The error type to get methods for
            category: Optional filter by category
            difficulty: Optional filter by difficulty level

        Returns:
            List of training method dictionaries
        """
        info = self.get_error_type_info(error_type)
        if not info:
            return []

        methods = info.get("training_methods", [])

        # Apply filters
        if category:
            methods = [
                m for m in methods if m.get("category", "").lower() == category.lower()
            ]

        if difficulty:
            methods = [
                m
                for m in methods
                if m.get("difficulty", "").lower() == difficulty.lower()
            ]

        return methods

    def get_training_method_categories(self, error_type: str) -> List[str]:
        """Get unique categories of training methods for an error type."""
        info = self.get_error_type_info(error_type)
        if not info:
            return []

        methods = info.get("training_methods", [])
        categories = list(set(m.get("category", "Other") for m in methods))
        return sorted(categories)

    def get_evaluation_metrics(self, error_type: str) -> List[str]:
        """Get evaluation metrics for an error type."""
        info = self.get_error_type_info(error_type)
        if not info:
            return []
        return info.get("evaluation_metrics", [])

    def add_training_method(
        self,
        error_type: str,
        method: Dict[str, Any],
    ) -> bool:
        """
        Add a new training method to an error type.

        Args:
            error_type: The error type to add the method to
            method: Dictionary with method details (name, category, description, etc.)

        Returns:
            True if added successfully, False otherwise
        """
        if not self._data:
            return False

        error_types = self._data.get("error_types", {})

        # Find the error type (case-insensitive)
        target_key = None
        for key in error_types:
            if key.lower() == error_type.lower():
                target_key = key
                break

        if not target_key:
            log.warning("Error type not found: %s", error_type)
            return False

        # Validate method has required fields
        required_fields = ["name", "description"]
        for field in required_fields:
            if field not in method:
                log.warning("Missing required field: %s", field)
                return False

        # Add default values
        method.setdefault("category", "Other")
        method.setdefault("difficulty", "intermediate")
        method.setdefault("effect", "")
        method.setdefault("reference", None)

        # Add to training methods
        if "training_methods" not in error_types[target_key]:
            error_types[target_key]["training_methods"] = []

        error_types[target_key]["training_methods"].append(method)

        return self._save()

    def update_training_method(
        self,
        error_type: str,
        method_name: str,
        updates: Dict[str, Any],
    ) -> bool:
        """
        Update an existing training method.

        Args:
            error_type: The error type containing the method
            method_name: Name of the method to update
            updates: Dictionary of fields to update

        Returns:
            True if updated successfully, False otherwise
        """
        info = self.get_error_type_info(error_type)
        if not info:
            return False

        methods = info.get("training_methods", [])

        for method in methods:
            if method.get("name", "").lower() == method_name.lower():
                method.update(updates)
                return self._save()

        log.warning("Method not found: %s in %s", method_name, error_type)
        return False

    def add_quick_fix(self, error_type: str, quick_fix: str) -> bool:
        """Add a quick fix suggestion to an error type."""
        if not self._data:
            return False

        error_types = self._data.get("error_types", {})

        # Find the error type
        target_key = None
        for key in error_types:
            if key.lower() == error_type.lower():
                target_key = key
                break

        if not target_key:
            return False

        if "quick_fixes" not in error_types[target_key]:
            error_types[target_key]["quick_fixes"] = []

        if quick_fix not in error_types[target_key]["quick_fixes"]:
            error_types[target_key]["quick_fixes"].append(quick_fix)
            return self._save()

        return True  # Already exists

    def get_solutions_summary(self, error_type: str) -> Dict[str, Any]:
        """
        Get a complete summary of solutions for an error type.

        Returns a dictionary suitable for the frontend suggestion window.
        Separates test-time methods (no training required) from training methods.
        """
        info = self.get_error_type_info(error_type)
        if not info:
            return {
                "error_type": error_type,
                "found": False,
                "quick_fixes": [],
                "test_time_methods": [],
                "test_time_methods_by_category": {},
                "test_time_categories": [],
                "training_methods": [],
                "training_methods_by_category": {},
                "categories": [],
                "evaluation_metrics": [],
            }

        # Get test-time methods (no training required) and enrich with citations
        test_time_methods = self._enrich_methods_with_citations(
            info.get("test_time_methods", [])
        )
        test_time_categories = {}
        for method in test_time_methods:
            cat = method.get("category", "Other")
            if cat not in test_time_categories:
                test_time_categories[cat] = []
            test_time_categories[cat].append(method)

        # Get training methods and enrich with citations
        training_methods = self._enrich_methods_with_citations(
            info.get("training_methods", [])
        )
        training_categories = {}
        for method in training_methods:
            cat = method.get("category", "Other")
            if cat not in training_categories:
                training_categories[cat] = []
            training_categories[cat].append(method)

        return {
            "error_type": error_type,
            "found": True,
            "display_name": info.get("display_name", error_type),
            "description": info.get("description", ""),
            "severity_default": info.get("severity_default", "medium"),
            "quick_fixes": info.get("quick_fixes", []),
            "test_time_methods": test_time_methods,
            "test_time_methods_by_category": test_time_categories,
            "test_time_categories": list(test_time_categories.keys()),
            "training_methods": training_methods,
            "training_methods_by_category": training_categories,
            "categories": list(training_categories.keys()),
            "evaluation_metrics": info.get("evaluation_metrics", []),
        }

    def get_difficulty_levels(self) -> Dict[str, Dict[str, str]]:
        """Get difficulty level definitions."""
        if not self._data:
            return {}
        return self._data.get("difficulty_levels", {})

    def export_data(self) -> Dict[str, Any]:
        """Export the entire knowledge base."""
        return self._data or {}

    def import_data(self, data: Dict[str, Any], merge: bool = False) -> bool:
        """
        Import data into the knowledge base.

        Args:
            data: Data to import
            merge: If True, merge with existing data; if False, replace

        Returns:
            True if imported successfully
        """
        try:
            if merge and self._data:
                # Merge error types
                existing_types = self._data.get("error_types", {})
                new_types = data.get("error_types", {})

                for error_type, info in new_types.items():
                    if error_type in existing_types:
                        # Merge training methods
                        existing_methods = existing_types[error_type].get(
                            "training_methods", []
                        )
                        new_methods = info.get("training_methods", [])
                        existing_names = {m.get("name") for m in existing_methods}

                        for method in new_methods:
                            if method.get("name") not in existing_names:
                                existing_methods.append(method)

                        existing_types[error_type][
                            "training_methods"
                        ] = existing_methods

                        # Merge quick fixes
                        existing_fixes = existing_types[error_type].get(
                            "quick_fixes", []
                        )
                        new_fixes = info.get("quick_fixes", [])
                        for fix in new_fixes:
                            if fix not in existing_fixes:
                                existing_fixes.append(fix)
                        existing_types[error_type]["quick_fixes"] = existing_fixes
                    else:
                        existing_types[error_type] = info
            else:
                self._data = data

            return self._save()
        except Exception as e:
            log.error("Failed to import data: %s", e)
            return False


# Singleton instance
_kb_instance: Optional[ErrorSolutionsKnowledgeBase] = None


def get_knowledge_base() -> ErrorSolutionsKnowledgeBase:
    """Get the singleton knowledge base instance."""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = ErrorSolutionsKnowledgeBase()
    return _kb_instance


# Convenience functions
def get_solutions_for_error_type(error_type: str) -> Dict[str, Any]:
    """Get complete solutions summary for an error type."""
    return get_knowledge_base().get_solutions_summary(error_type)


def get_all_error_types() -> List[str]:
    """Get list of all error types."""
    return get_knowledge_base().get_all_error_types()


def get_training_methods(
    error_type: str,
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get training methods for an error type."""
    return get_knowledge_base().get_training_methods(error_type, category, difficulty)


def add_training_method(error_type: str, method: Dict[str, Any]) -> bool:
    """Add a training method to an error type."""
    return get_knowledge_base().add_training_method(error_type, method)
