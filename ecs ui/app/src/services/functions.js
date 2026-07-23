export const extractLastTwo = (path) => {
  const parts = path.split('/').filter(Boolean); // removes empty strings
  if (parts.length < 3) return parts?.join('-');
  return `${parts[parts.length - 3]}-${parts[parts.length - 2]}`;
}

export const getUserDetails = () => {
  const profileData = JSON.parse(localStorage.getItem("UserProfile"));
  const userProfile = profileData?.value;
  let user_id = null;
  let user_name = null;
  let ask_ai_user_id = null;
  let user_folder_id = null;
  let idToken = null;
  let gmail = null;
  let full_name = null;
  let isContractor = false;
  let isAdminID = false;

  if (userProfile) {
    user_name = extractNameFromEmail(userProfile.name);
    user_id = userProfile.homeAccountId;
    ask_ai_user_id = userProfile.homeAccountId;
    user_folder_id = userProfile.homeAccountId;
    idToken = userProfile.idToken;
    gmail = userProfile.username;
    full_name = extractNameFromEmail(userProfile.username);
    var { firstName, lastName } = getFirstAndLastName(full_name);
    isContractor = !EXCLUDED_EMAILS.includes(gmail) && gmail.includes("-CW@otsuka-us.com");
    isAdminID = ADMIN_EMAILS.includes(gmail);


    // You can also call `fetchUserPhoto(accessToken)` if necessary
    // fetchUserPhoto(accessToken);

  }
  return { user_name, user_id, user_folder_id, ask_ai_user_id, idToken, gmail, full_name, firstName, lastName, isContractor, isAdminID };
};

export const downloadDocxFromBase64 = (base64, fileName = "download.docx") => {
  try {
    // convert base64 → binary
    const byteCharacters = atob(base64);
    const byteNumbers = new Array(byteCharacters.length);

    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }

    const byteArray = new Uint8Array(byteNumbers);
    // create blob
    const blob = new Blob([byteArray], {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    });

    // create download link
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = fileName;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

  } catch (err) {
    console.error("Download failed", err);
  }
};