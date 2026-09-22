import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import './app/style.css'
createApp(App).use(router).mount('#app')

