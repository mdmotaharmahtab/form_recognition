import React from "react";
import styled, { createGlobalStyle } from "styled-components";
import { Button, Row, Col, Space, Spin, Progress, Affix, Tooltip } from "antd";
import { FileOutlined } from "@ant-design/icons";
import UploadDoc from "./UploadDoc";
import TemplateTable from "./TemplateTable";
import { useECS } from "./useECS";
import VersionTable from "./VersionTable";

const GlobalStyle = createGlobalStyle`
  * {
    font-family: 'Open Sans', sans-serif !important;
  }
`;

const StyledButton = styled(Button)`
  background: #e3ecff;
  color: #426bba !important;
  font-weight: 600;
  font-size: 14px;
  border: none;
  border-radius: 1rem;
  box-shadow: 0 2px 6px rgba(66, 107, 186, 0.2);
  padding: 4px 16px;

  &:hover {
    background: #d7e4ff !important;
    color: #426bba !important;
  }
`;

const StyledProgress = styled(Progress)`
  .ant-progress-bg {
    background-color: #426bba !important; /* progress bar color */
  }

  .ant-progress-text {
    font-size: 11px !important; /* text size */
    color: #426bba !important; /* text color */
  }
`;

const SelectedFileName = ({ fileName, showIconOnly = false }) => {
  return (
    <Tooltip title={fileName}>
      <span
        style={{
          display: "flex",
          alignItems: "center",
          cursor: "pointer",
          justifyContent: "flex-start",
          overflow: "hidden",
          width: "100%",
          whiteSpace: "nowrap",
        }}
      >
        <FileOutlined style={{ fontSize: 18, fontSize: "12px", color: "#426bba", marginRight: 6 }} />
        {!showIconOnly && (
          <span
            style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              color: "#426bba",
              fontSize: "10px",
              display: "inline-block",
            }}
          >
            {fileName}
          </span>
        )}
      </span>
    </Tooltip>
  );
};

const UploadSourceDocument = () => {
  const {
    dataSource,
    columns,
    loading,
    onClickGenerate,
    handleBack,
    onBack,
    tip,
    isFileDigitized,
    progress,
    templateProgress,
    templateProgressCompleted,
    totalTemplate,
    templateLoading,
    fileList,
    versions,
    onSelectVersion
  } = useECS();

  const percentage = totalTemplate
    ? ((templateProgressCompleted / totalTemplate) * 100).toFixed(2)
    : 0;

  return (
    <div style={{ position: "relative", padding: "8px" }}>
      {templateLoading ? (
        <Affix offsetTop={2}>
          <div
            style={{
              background:
                "linear-gradient(150deg, rgba(235, 240, 255, 1) 25%, rgba(225, 235, 255, 1) 50%, rgba(215, 230, 255, 1) 100%)",
              padding: "8px 16px",
              color: "#426BBA",
              zIndex: 1000,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              background: "#e3ecff",
              color: "#426bba !important",
              fontSize: "12px",
              border: "none",
              borderRadius: "1rem",
              boxShadow: "0 2px 6px rgba(66, 107, 186, 0.2)",
              padding: "4px 16px",
              width: "80%",
              margin: "auto",
            }}
          >
            <div style={{ marginTop: 0, color: "#426bba", fontSize: "11px" }}>
              {templateProgressCompleted}/{totalTemplate} LLM generated
            </div>
            <div style={{ width: "35%" }}>
              <StyledProgress
                percent={percentage}
                status={percentage === 100 ? "success" : "active"}
                strokeColor="#426bba"
                style={{ color: "#426bba", fontSize: "12px" }}
              />
            </div>
            <div style={{ width: "7%", overflow: "hidden" }}>
              <SelectedFileName fileName={fileList?.[0]?.name} showIconOnly={true} />
            </div>
          </div>
        </Affix>
      ) : (
        <div style={{ display: "flex", alignItems: "center", marginBottom: "8px", gap: "2rem" }}>
          <StyledButton type="primary" onClick={handleBack} disabled={loading}>
            Back
          </StyledButton>
          {fileList?.[0]?.name && <SelectedFileName fileName={fileList?.[0]?.name} />}
        </div>
      )}

      <Row justify="center" style={{ padding: "8px", paddingBottom: "2rem" }}>
        <GlobalStyle />
        <Col xs={24} sm={18} md={12} lg={8}>
          <Space direction="vertical" size="large" style={{ width: "100%", textAlign: "center" }}>
            <Spin
              spinning={loading}
              tip={
                progress > 0 && progress < 100 ? (
                  <div style={{ textAlign: "center" }}>
                    <div style={{ marginBottom: 8 }}>{tip}</div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <div style={{ width: "70%" }}>
                        <Progress percent={progress} size="small" />
                      </div>
                    </div>
                  </div>
                ) : (
                  tip
                )
              }
            >
              {dataSource.length > 0 ? (
                <>
                  {/* <div style={{ display: "flex", marginBottom: 20 }}>
                    {<StyledButton type="text" onClick={handleInsertAll}>
                      Write All to Excel
                    </StyledButton>}
                  </div> */}
                  <TemplateTable columns={columns} dataSource={dataSource} />
                </>
              ) : (
                <>
                  <UploadDoc />
                  {versions?.length > 0 && <VersionTable versions={versions} loading={loading} onSelectVersion={onSelectVersion} />}
                  {/* {isFileDigitized && (
                    <StyledButton type="primary" onClick={onClickGenerate}>
                      Generate ECS Mapping
                    </StyledButton>
                  )} */}
                </>
              )}
            </Spin>
          </Space>
        </Col>
      </Row>
    </div>
  );
};

export default UploadSourceDocument;
