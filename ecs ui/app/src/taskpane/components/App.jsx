import * as React from "react";
import PropTypes from "prop-types";
import { makeStyles } from "@fluentui/react-components";
// import { getDocumentName } from "../taskpane";
import Taskpane from "./Taskpane";
import { AuthProvider } from "../contexts/AuthContext";
import "jspreadsheet-ce/dist/jspreadsheet.css";
import { RoleProvider } from "../contexts/RoleContext";

const useStyles = makeStyles({
  root: {
    minHeight: "100vh",
    background:
      "linear-gradient(150deg, rgba(247, 250, 255, 1) 25%, rgba(240, 245, 255, 1) 50%, rgba(227, 236, 255, 1) 100%)",
  },
});

const App = (props) => {
  const { title } = props;
  const styles = useStyles();
  const [docName, setDocName] = React.useState("");

  // React.useEffect(() => {
  //   const fetchDocumentName = async () => {
  //     try {
  //       const name = await getDocumentName();
  //       setDocName(name || "Report ID not found");
  //     } catch (error) {
  //       console.error("Failed to get document name:", error);
  //     }
  //   };
  //   fetchDocumentName();
  // }, []);

  return (
    <div className={styles.root}>
      <AuthProvider>
        <RoleProvider>
          <Taskpane documentName={docName} />
        </RoleProvider>
      </AuthProvider>
    </div>
  );
};

App.propTypes = {
  title: PropTypes.string,
};

export default App;
