import React, { createContext, useContext, useState } from "react";

const RoleContext = createContext();

export const RoleProvider = ({ children }) => {
  const [selectedRole, setSelectedRole] = useState(null);
  const [userSelected, setUserSelected] = useState(false);
  const [accessibleProjects, setAccessibleProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [monitoringSelected, setMonitoringSelected] = useState(false);

  return (
    <RoleContext.Provider
      value={{
        userSelected,
        setUserSelected,
        selectedRole,
        setSelectedRole,
        selectedProject,
        setSelectedProject,
        accessibleProjects,
        setAccessibleProjects,
        monitoringSelected,
        setMonitoringSelected
      }}
    >
      {children}
    </RoleContext.Provider>
  );
};

export const useRole = () => useContext(RoleContext);
