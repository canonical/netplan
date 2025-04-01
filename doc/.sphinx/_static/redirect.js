// Function to capture and log the current URL
function logOldUrl() {
  const oldUrl = window.location.href;
  const hash = window.location.hash;
  console.log("Old URL before redirect:", oldUrl, hash);
}

// Add an event listener to capture the URL before unloading the page
window.addEventListener("beforeunload", logOldUrl);

window.onload = logOldUrl;

// Optionally, listen for visibility changes to detect potential navigation changes
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    logOldUrl();
  }
});

logOldUrl();
