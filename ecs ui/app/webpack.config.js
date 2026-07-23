const devCerts = require("office-addin-dev-certs");
const CopyWebpackPlugin = require("copy-webpack-plugin");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const webpack = require("webpack");
const path = require("path");
const dotenv = require("dotenv").config();

const { Frontend_LOCAL_PROXY } = require("./constant.js");
const urlDev = Frontend_LOCAL_PROXY
const urlProd = "https://www.contoso.com/"; // CHANGE THIS TO YOUR PRODUCTION DEPLOYMENT LOCATION

async function getHttpsOptions() {
  const httpsOptions = await devCerts.getHttpsServerOptions();
  return { ca: httpsOptions.ca, key: httpsOptions.key, cert: httpsOptions.cert };
}

module.exports = async (env, options) => {
  const dev = options.mode === "development";
  const config = {
    devtool: "source-map",
    entry: {
      polyfill: ["core-js/stable", "regenerator-runtime/runtime"],
      vendor: ["react", "react-dom", "core-js", "@fluentui/react-components", "@fluentui/react-icons"],
      taskpane: "./src/taskpane/index.jsx",
      commands: "./src/commands/commands.js",
      ECS: ["./src/taskpane/components/ECS.jsx", "./src/taskpane/ecs.html"],
      Pvc: ["./src/taskpane/components/Pvc/index.jsx", "./src/taskpane/pvc.html"],
      PvcReviewDialog: ["./src/taskpane/components/Pvc/PvcReviewDialog.jsx", "./src/taskpane/PvcReviewDialog.html"],
      MonitoringDialog: ["./src/taskpane/components/User/MonitoringDialog.jsx", "./src/taskpane/MonitoringDialog.html"],
    },
    output: {
      clean: true,
      path: path.resolve(__dirname, "dist"),
      filename: "[name].[contenthash].js",
      chunkFilename: "[name].[contenthash].chunk.js",
    },
    resolve: {
      extensions: [".js", ".jsx", ".html"],
      fallback: {
        process: require.resolve("process/browser"),
      },
    },
    module: {
      rules: [
        {
          test: /\.css$/i,
          use: ["style-loader", "css-loader"],
        },
        {
          test: /\.jsx?$/,
          use: {
            loader: "babel-loader",
            options: {
              presets: ["@babel/preset-env", "@babel/preset-react"], // Added @babel/preset-react for JSX support
            },
          },
          exclude: /node_modules/,
        },
        {
          test: /\.html$/,
          exclude: /node_modules/,
          use: "html-loader",
        },
        {
          test: /\.(svg|png|jpg|jpeg|ttf|woff|woff2|gif|ico)$/,
          type: "asset/resource",
          generator: {
            filename: "assets/[name][ext][query]",
          },
        },
      ],
    },
    plugins: [
      new CopyWebpackPlugin({
        patterns: [
          {
            from: "assets/*",
            to: "assets/[name][ext][query]",
          },
          {
            from: "manifest*.xml",
            to: "[name]" + "[ext]",
            transform(content) {
              if (dev) {
                return content;
              } else {
                return content.toString().replace(new RegExp(urlDev, "g"), urlProd);
              }
            },
          },
        ],
      }),
      new HtmlWebpackPlugin({
        filename: "taskpane.html",
        template: "./src/taskpane/taskpane.html",
        chunks: ["polyfill", "vendor", "taskpane"],
      }),
      new HtmlWebpackPlugin({
        filename: "ecs.html",
        template: "./src/taskpane/ecs.html",
        chunks: ["ECS"],
      }),
      new HtmlWebpackPlugin({
        filename: "pvc.html",
        template: "./src/taskpane/pvc.html",
        chunks: ["polyfill", "vendor", "Pvc"],
      }),
      new HtmlWebpackPlugin({
        filename: "PvcReviewDialog.html",
        template: "./src/taskpane/PvcReviewDialog.html",
        chunks: ["polyfill", "vendor", "PvcReviewDialog"],
      }),
      new HtmlWebpackPlugin({
        filename: "MonitoringDialog.html",
        template: "./src/taskpane/MonitoringDialog.html",
        chunks: ["polyfill", "vendor", "MonitoringDialog"],
      }),
      new webpack.ProvidePlugin({
        process: "process/browser.js",
        Promise: ["es6-promise", "Promise"],
      }),
      new webpack.DefinePlugin({
        "process.env.REACT_APP_BASE_URL": JSON.stringify(process.env.REACT_APP_BASE_URL),
        "process.env.REACT_API_BASE_URL": JSON.stringify(process.env.REACT_API_BASE_URL),
        "process.env.REACT_APP_ECS_PLATFORM_TOKEN": JSON.stringify(process.env.REACT_APP_ECS_PLATFORM_TOKEN),
        "process.env.REACT_APP_ECS_PLATFORM_URL": JSON.stringify(process.env.REACT_APP_ECS_PLATFORM_URL),
        "process.env.REACT_APP_ECS_UTILS_TOKEN": JSON.stringify(process.env.REACT_APP_ECS_UTILS_TOKEN),
        "process.env.REACT_APP_ECS_UTILS_URL": JSON.stringify(process.env.REACT_APP_ECS_UTILS_URL),
        "process.env.REACT_ASK_BASE_URL": JSON.stringify(process.env.REACT_ASK_BASE_URL),
        "process.env.REACT_ASK_URL_PATH": JSON.stringify(process.env.REACT_ASK_URL_PATH),
        "process.env.REACT_ASK_URL_TOKEN": JSON.stringify(process.env.REACT_ASK_URL_TOKEN),
        "process.env.REACT_APP_CCM_API_BASE_URL": JSON.stringify(process.env.REACT_APP_CCM_API_BASE_URL),
        "process.env.REACT_APP_CCM_URL_TOKEN": JSON.stringify(process.env.REACT_APP_CCM_URL_TOKEN),
        "process.env.REACT_APP_CCM_UTILS_TOKEN": JSON.stringify(process.env.REACT_APP_CCM_UTILS_TOKEN),
      }),
    ],
    devServer: {
      hot: true,
      allowedHosts: "all",
      headers: {
        "Access-Control-Allow-Origin": "*",
      },
      // ── Reverse proxy: /api/* → CCM backend ────────────────────────────
      proxy: [
        {
          context: ["/api"],
          target: "https://api-aiwriter-services-dev.otsuka-us.com",
          changeOrigin: true,
          secure: true,
          pathRewrite: { "^/api": "/ccm-processing-dev/public/api" },
          onProxyReq: (proxyReq) => {
            proxyReq.setHeader("Host", "api-aiwriter-services-dev.otsuka-us.com");
          },
        },
        {
          context: ["/ccm-utils"],
          target: "https://api-aiwriter-services-dev.otsuka-us.com",
          changeOrigin: true,
          secure: true,
          pathRewrite: { "^/ccm-utils": "/ccm-utils/public/api" },
          onProxyReq: (proxyReq) => {
            proxyReq.setHeader("Host", "api-aiwriter-services-dev.otsuka-us.com");
          },
        },
      ],
      // ───────────────────────────────────────────────────────────────────
      server: {
        type: "https",
        options: env.WEBPACK_BUILD || options.https !== undefined ? options.https : await getHttpsOptions(),
      },
      port: process.env.npm_package_config_dev_server_port || 3000,
    },
  };

  return config;
};
