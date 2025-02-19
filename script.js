// External JS file moved from template.html for better organization.

$(document).ready(function () {
    // Initialize DataTables for the repositories table.
    $('#repoTable').DataTable({
        paging: false,
        order: [[3, "desc"]],  // Order by "Last Commit" descending
        columns: [
            null,                    // Repository: default text type
            {type: "num-fmt"},      // Open Issues: numeric formatted
            {type: "num-fmt"},      // Open PRs: numeric formatted
            {type: "num"},          // Last Commit: date
            null                     // Status: default text type
        ]
    });
    // Initialize DataTables for the contributors table.
    $('#contribTable').DataTable({
        paging: false,
        order: [[1, "desc"]],  // Order by "Open Issues" descending
        columns: [
            null,                    // Contributor: default text type
            {type: "num-fmt"},      // Open Issues: numeric formatted
            {type: "num-fmt"}       // Open PRs: numeric formatted
        ]
    });
});

// Function to switch between dashboard tabs.
function openTab(evt, tabName) {
    var i, tabcontent, tablinks;
    tabcontent = document.getElementsByClassName("tabcontent");
    // Hide all tab content sections.
    for (i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
    }
    tablinks = document.getElementsByClassName("tablinks");
    // Remove the active class from all tab buttons.
    for (i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
    }
    // Display the current tab and mark the button as active.
    document.getElementById(tabName).style.display = "block";
    evt.currentTarget.className += " active";
}
