import React, { useEffect, useState } from "react";
import { Col, Row, Select, Space } from "antd";
import styled from "styled-components";
import { MY_PROJECTS, ROLE_MAP } from "../../../constant";
import ECS from "./ECS";
import FloatingChatBot from "./Ecs/FloatingChatBot";
import otsukaLogo from "./../../../assets/otsuka.png";
import GroupLogo from "./../../../assets/Group.png";
import Pvc from "./Pvc";
import { useRole } from "../contexts/RoleContext";
import { getAccess } from "../../services/ccmApiService";

const { Option } = Select;

const getRoleName = (roleId) => {
  return ROLE_MAP[roleId] || "UNKNOWN_ROLE";
};

export const StyledSelect = styled(Select)`
  width: 90%;
  height: auto;
  font-size: 14px;
  font-weight: 600;
  color: #426bba;
  border-radius: 1rem !important;
  box-shadow: 0 2px 6px rgba(66, 107, 186, 0.2);

  && .ant-select-selector {
    background-color: #e3ecff !important;
    border: none !important;
    border-radius: 1rem !important;
    padding: 4px 16px;
    color: #426bba !important;
  }

  && .ant-select-selection-item,
  && .ant-select-selection-placeholder {
    color: #426bba !important;
  }

  && .ant-select-arrow {
    color: #426bba !important;

    svg {
      fill: #426bba !important;
    }
  }

  && .ant-select-dropdown {
    background-color: #e3ecff;
    color: #426bba;
    border-radius: 1rem;
  }

  && .ant-select-item-option-content {
    color: #426bba;
  }

  &:hover .ant-select-selector {
    background-color: #d7e4ff !important;
    color: #426bba !important;
  }
`;

const SelectDeliverable = ({ email }) => {
  const [selectedForm, setSelectedForm] = useState(null);
  const [loading, setLoading] = useState(false);

  const { setSelectedRole, setSelectedProject, accessibleProjects, setAccessibleProjects } = useRole();

  useEffect(() => {
    fetchAccess();
  }, []);

  const fetchAccess = async () => {
    try {
      setLoading(true);
      const response = await getAccess({ email });

      const filteredProjects =
        response?.access?.filter((item) => item?.has_access === "true" && MY_PROJECTS.includes(item.project_name)) ||
        [];

      setAccessibleProjects(filteredProjects);
    } catch (error) {
      console.log("ACCESS API ERROR", error);
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = (selectedProjectName) => {
    const selectedProject = accessibleProjects.find((item) => item.project_name === selectedProjectName);

    const roleName = getRoleName(selectedProject?.role);

    setSelectedRole(roleName);
    setSelectedForm(selectedProjectName);
    setSelectedProject(selectedProject);
  };

  const goBack = () => {
    setSelectedForm(null);
  };

  return (
    <>
      {selectedForm === null && (
        <>
          <Row justify="center" style={{ padding: "16px" }}>
            <Col xs={24} sm={18} md={12} lg={8}>
              <Space direction="vertical" size="large" style={{ width: "100%", textAlign: "center", marginTop: 100 }}>
                <img src={otsukaLogo} alt="otsukaLogo" style={{ marginRight: 16, width: "45%" }} />

                <StyledSelect
                  placeholder="Select Deliverable"
                  onChange={handleSelect}
                  loading={loading}
                  disabled={loading}
                  notFoundContent={loading ? "Loading deliverable..." : "No deliverable found"}
                >
                  {accessibleProjects.map((project) => (
                    <Option key={project.project_id} value={project.project_name}>
                      {project?.project_label?.trim() || project.project_name}
                    </Option>
                  ))}
                </StyledSelect>
              </Space>
            </Col>
          </Row>
        </>
      )}

      {selectedForm === "ECS" && <ECS onBack={goBack} />}

      {selectedForm === "CCM" && <Pvc onBack={goBack} />}

      <FloatingChatBot />

      <img
        src={GroupLogo}
        alt="Group Logo"
        style={{
          position: "absolute",
          bottom: "0px",
          right: "0px",
          zIndex: 0,
          pointerEvents: "none",
        }}
      />
    </>
  );
};

export default SelectDeliverable;
