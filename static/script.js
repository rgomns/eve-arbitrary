function sortTable(columnIndex) {
    var table = document.getElementById("tradeTable");
    var rows = Array.from(table.rows).slice(1);
    var sortedRows = rows.sort((a, b) => {
        var valA = a.cells[columnIndex].innerText.replace('%', '');
        var valB = b.cells[columnIndex].innerText.replace('%', '');
        return !isNaN(valA) && !isNaN(valB) ? valB - valA : valA.localeCompare(valB);
    });
    sortedRows.forEach(row => table.appendChild(row));
}

document.addEventListener("DOMContentLoaded", () => {
        const sourceInput = document.getElementById("source_station_search");
        const sourceDropdown = document.getElementById("source_station_dropdown");

        const destInput = document.getElementById("dest_station_search");
        const destDropdown = document.getElementById("dest_station_dropdown");

        function fetchStations(input, dropdown) {
            const query = input.value.trim();
            if (query.length > 2) {
                fetch(`/search_station/?query=${query}`)
                    .then(response => response.json())
                    .then(data => {
                        dropdown.innerHTML = "";  // Clear previous results
                        data.forEach(station => {
                            const option = document.createElement("option");
                            option.value = station.station_id;
                            option.textContent = `${station.name} (ID: ${station.station_id})`;
                            dropdown.appendChild(option);
                        });
                    })
                    .catch(error => console.error("Error fetching stations:", error));
            }
        }

        sourceInput.addEventListener("keyup", () => fetchStations(sourceInput, sourceDropdown));
        destInput.addEventListener("keyup", () => fetchStations(destInput, destDropdown));
});