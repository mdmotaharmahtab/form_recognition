import { PublicClientApplication } from "@azure/msal-browser";
import { Frontend_LOCAL_PROXY } from "../constant";

const msalConfig = {
  auth: {
    clientId: "382c670c-e747-43ed-a40a-455b4f9a4dd6", // Azure AD App Registration (Client ID)
    authority: "https://login.microsoftonline.com/34ddb339-7fd0-4f00-9041-c2e47fbbc9f4", // Tenant ID or common
    redirectUri: `${Frontend_LOCAL_PROXY}/taskpane.html`, // must match Azure registered redirect URI
  },
  cache: {
    cacheLocation: "sessionStorage", // or "localStorage" if persistence needed
    storeAuthStateInCookie: false,   // set true if issues on IE/Edge
  },
};

const msalInstance = new PublicClientApplication(msalConfig);

const loginRequest = {
  scopes: ["User.Read"],
};

export { msalInstance, loginRequest };
