import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button, Drawer, Input, List, Avatar, Spin } from "antd";
import { MessageOutlined, SendOutlined, CloseOutlined } from "@ant-design/icons";
import skAILogo from "./../../../../assets/skAILogo.png";
import Illustration from "./../../../../assets/Illustration.png";
import { createNewChatSession, getAskAIResponse, renameSession } from "../../../services";
import { createGlobalStyle } from "styled-components";
import { marked } from "marked";
import { useAuth } from "../../contexts/AuthContext";

const { TextArea } = Input;

const GlobalStyle = createGlobalStyle`
  * {
    font-family: 'Open Sans', sans-serif !important;
  }
`;

const FloatingChatBot = () => {
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [session_id, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [userInput, setUserInput] = useState("");

  const { user } = useAuth();
  const user_id = user?.homeAccountId;

  const chatAreaRef = useRef(null);
  const executedIds = useRef(new Set());

  const toggleChat = () => setVisible((prev) => !prev);

  const handleClose = () => {
    toggleChat();
    setMessages([]);
  };

  const renameChatSession = useCallback(
    async (userInput) => {
      if (!executedIds.current.has(session_id)) {
        const session_name = userInput.trim();
        await renameSession(session_id, session_name);
        executedIds.current.add(session_id);
      }
    },
    [session_id]
  );

  const handleSend = async () => {
    const trimmed = userInput.trim();
    if (!trimmed) return;

    const payload = {
      query: trimmed,
      user_folder_id: user_id,
      default_llm_model: "azureopenai:Azure-OpenAi:gpt-4o",
      configs: {
        session_id: session_id,
        user_id: user_id,
      },
    };

    setLoading(true);

    try {
      const response = await getAskAIResponse(payload);
      renameChatSession(userInput);
      const newMessages = [...messages, { type: "user", text: trimmed }, { type: "bot", text: `${response?.message}` }];
      setMessages(newMessages);
      setUserInput("");
      setLoading(false);
    } catch (error) {
      console.log("error: ", error);
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible) {
      const payload = {
        user_id,
        configs: {
          doc_type: "AiWriter",
        },
      };
      createNewChatSession(payload)
        .then((res) => setSessionId(res.session_id))
        .catch((error) => console.log(error));
    }
  }, [visible]);

  useEffect(() => {
    if (chatAreaRef.current) {
      chatAreaRef.current.scrollTop = chatAreaRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <>
      <GlobalStyle />
      {/* Floating Chat Icon */}
      <Button
        shape="circle"
        icon={<MessageOutlined />}
        size="medium"
        style={{
          position: "fixed",
          bottom: 20,
          left: 20,
          zIndex: 1000,
          background: "#426BBA",
          borderColor: "#426BBA",
          color: "white",
        }}
        onClick={handleClose}
      />

      {/* Fullscreen Chat Drawer */}

      <Drawer
        open={visible}
        onClose={handleClose}
        placement="bottom"
        height="100vh"
        closable={false}
        maskClosable={true}
        bodyStyle={{
          padding: 0,
          background:
            "linear-gradient(150deg, rgba(247, 250, 255, 1) 25%, rgba(240, 245, 255, 1) 50%, rgba(227, 236, 255, 1) 100%)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Header */}
        <CloseOutlined
          onClick={handleClose}
          style={{
            position: "absolute",
            top: 16,
            right: 16,
            fontSize: 20,
            color: "#555",
            cursor: "pointer",
            zIndex: 2000, // higher than scroll content
          }}
        />

        {/* Header (logo only now) */}
        <div
          style={{
            height: 56,
            display: "flex",
            alignItems: "center",
            padding: "0 16px",
          }}
        >
          <img src={skAILogo} alt="skAILogo" style={{ width: "50px" }} />
        </div>
        {/* Chat Content Wrapper */}
        <div style={{ flex: 1, position: "relative" }}>
          <div
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "12px 16px",
              scrollBehavior: "smooth", // 👈 smoother scroll
              height: "100%", // important for scroll
            }}
            id="chatScrollArea"
          >
            <List
              dataSource={messages}
              locale={{
                emptyText: (
                  <div style={{ textAlign: "center", padding: "40px 0" }}>
                    <img src={Illustration} alt="No messages" style={{ width: "250px" }} />
                    <div style={{ marginTop: 12, color: "#888" }}>No Messages</div>
                  </div>
                ),
              }}
              renderItem={(item) => (
                <List.Item
                  style={{
                    justifyContent: item.type === "user" ? "flex-end" : "flex-start",
                  }}
                >
                  <List.Item.Meta
                    avatar={item.type === "user" ? null : <Avatar src={skAILogo} style={{ height: "unset" }} />}
                    description={<div dangerouslySetInnerHTML={{ __html: marked(item.text) }} />}
                    style={{
                      padding: "8px 12px",
                      borderRadius: 8,
                      textAlign: item.type === "user" ? "right" : "left",
                      wordBreak: "break-word",
                    }}
                    className={item.type === "user" ? "user-prompt" : "prompt-reponse"}
                  />
                </List.Item>
              )}
            />
          </div>

          {/* Fixed Centered Loader */}
          {loading && (
            <div
              style={{
                position: "fixed",
                inset: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "rgba(255,255,255,0.4)",
                zIndex: 10,
              }}
            >
              <Spin size="medium" />
            </div>
          )}
        </div>

        {/* Input Area with TextArea + Send Button */}
        <div
          ref={chatAreaRef}
          style={{
            padding: "12px 16px",
            // borderTop: '1px solid #ccc',
            // background: '#D4DFF0',
          }}
        >
          <div style={{ display: "flex", gap: 8 }}>
            <TextArea
              value={userInput}
              onChange={(e) => setUserInput(e.target.value)}
              placeholder="Type your message..."
              autoSize={{ minRows: 2, maxRows: 6 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              style={{ resize: "none", flex: 1 }}
            />
            <Button
              icon={<SendOutlined />}
              onClick={handleSend}
              type="primary"
              style={{
                background: "#426BBA",
                borderColor: "#426BBA",
              }}
              disabled={loading || !userInput?.trim()}
            />
          </div>
        </div>
      </Drawer>
    </>
  );
};

export default FloatingChatBot;
