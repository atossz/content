from Utils.github_workflow_scripts.run_docs_review import pass_files_to_docs_review


class TestsRunDocsReview:

    def test_file_name_includes_apostrophe(self, capsys):
        """
            Given:
                - A string contains a file name with an apostrophe.
            When:
                - Running pass_files_to_docs_review function of the run_docs_review github workflow script.
            Then:
                - Verify the doc reviewer gets the file name with the apostrophe correctly.
                - Verify that the output is as expected.
        """
        file_name = "Process_Microsoft's_Anti-Spam_Headers"  # name includes apostrophe
        sdk_docs_reviewer_starting_string = '================= Starting Doc Review ================='
        expected_exit_code_of_run_docs_review = 0

        result = pass_files_to_docs_review([file_name])
        captured = capsys.readouterr()
        assert sdk_docs_reviewer_starting_string in captured.out
        assert file_name in captured.out
        assert result == expected_exit_code_of_run_docs_review
