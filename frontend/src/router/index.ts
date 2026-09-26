import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { session, type Role } from '../features/auth/session'
import { createAuthGuard } from './guards'
import AppLayout from '../app/AppLayout.vue'

declare module 'vue-router' {
  interface RouteMeta { public?:boolean;guest?:boolean;roles?:Role[] }
}
const routes:RouteRecordRaw[]=[
  {path:'/login',component:()=>import('../features/auth/LoginPage.vue'),meta:{public:true,guest:true}},
  {path:'/register',component:()=>import('../features/auth/RegisterPage.vue'),meta:{public:true,guest:true}},
  {path:'/status',component:()=>import('../app/HealthPage.vue'),meta:{public:true}},
  {path:'/session-error',component:()=>import('../app/StatePage.vue'),props:{kind:'session-error'},meta:{public:true}},
  {path:'/forbidden',component:()=>import('../app/StatePage.vue'),props:{kind:'forbidden'},meta:{public:true}},
  {path:'/',component:AppLayout,children:[
    {path:'',component:()=>import('../app/RoleHome.vue')},
    {path:'user',component:()=>import('../app/RoleHome.vue'),meta:{roles:['user']}},
    {path:'agent',component:()=>import('../app/RoleHome.vue'),meta:{roles:['agent']}},
    {path:'admin',component:()=>import('../app/RoleHome.vue'),meta:{roles:['admin']}},
    {path:'admin/users',component:()=>import('../features/users/UserListPage.vue'),meta:{roles:['admin']}},
    {path:'knowledge',component:()=>import('../features/knowledge/KnowledgeListPage.vue')},
    {path:'knowledge/:id',component:()=>import('../features/knowledge/KnowledgeDetailPage.vue')},
    {path:'chat/:id?',component:()=>import('../features/chat/ChatPage.vue')},
  ]},
  {path:'/:pathMatch(.*)*',component:()=>import('../app/StatePage.vue'),props:{kind:'not-found'},meta:{public:true}},
]
export const router=createRouter({history:createWebHistory(),routes})
router.beforeEach(createAuthGuard(session))
