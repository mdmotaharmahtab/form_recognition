# Build stage
FROM public.ecr.aws/docker/library/node:22 AS builder

# Set build arguments
ARG ENV_NAME
ARG REACT_APP_BASE_URL
ARG REACT_API_BASE_URL
ARG REACT_APP_ECS_PLATFORM_TOKEN
ARG REACT_APP_ECS_PLATFORM_URL
ARG REACT_APP_ECS_UTILS_TOKEN
ARG REACT_APP_ECS_UTILS_URL
ARG REACT_ASK_BASE_URL
ARG REACT_ASK_URL_PATH
ARG REACT_ASK_URL_TOKEN
ARG REACT_APP_CCM_API_BASE_URL
ARG REACT_APP_CCM_URL_TOKEN
ARG BUILD_NUMBER
ARG REACT_APP_CCM_UTILS_TOKEN

# Set environment variables
ENV NODE_ENV=development \
    REACT_APP_BASE_URL=${REACT_APP_BASE_URL} \
    REACT_API_BASE_URL=${REACT_API_BASE_URL} \
    REACT_APP_ECS_PLATFORM_TOKEN=${REACT_APP_ECS_PLATFORM_TOKEN} \
    REACT_APP_ECS_PLATFORM_URL=${REACT_APP_ECS_PLATFORM_URL} \
    REACT_APP_ECS_UTILS_TOKEN=${REACT_APP_ECS_UTILS_TOKEN} \
    REACT_APP_ECS_UTILS_URL=${REACT_APP_ECS_UTILS_URL} \
    REACT_ASK_BASE_URL=${REACT_ASK_BASE_URL} \
    REACT_ASK_URL_PATH=${REACT_ASK_URL_PATH} \
    REACT_ASK_URL_TOKEN=${REACT_ASK_URL_TOKEN} \
    REACT_APP_CCM_API_BASE_URL=${REACT_APP_CCM_API_BASE_URL} \
    REACT_APP_CCM_URL_TOKEN=${REACT_APP_CCM_URL_TOKEN} \
    REACT_APP_CCM_UTILS_TOKEN=${REACT_APP_CCM_UTILS_TOKEN}

WORKDIR /app

# Copy package files and install dependencies
COPY app/package*.json ./
RUN npm install 

# Workaround for deprecated dependencies (uncomment if necessary)
# RUN npm install --save --legacy-peer-deps
# ENV NODE_OPTIONS="--openssl-legacy-provider"

# Copy all project files excluding the ones specified in .dockerignore
COPY app/. .

# Build the application
RUN npm run build \
&& echo "{ \"version\": \"${BUILD_NUMBER}\" }" > dist/version.json

# Production image stage
FROM public.ecr.aws/nginx/nginx:mainline-alpine AS runner

WORKDIR /usr/share/nginx/html

# Copy the build output from the builder stage
COPY --from=builder /app/dist ./
COPY app/config/nginx.conf /etc/nginx/
COPY app/start.sh ./

# Start NGINX server using the start.sh script
CMD ["sh", "./start.sh"]